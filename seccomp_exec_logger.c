#define _GNU_SOURCE
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/unistd.h>
#include <sched.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SECCOMP_FILTER_FLAG_NEW_LISTENER
#define SECCOMP_FILTER_FLAG_NEW_LISTENER (1UL << 3)
#endif
#ifndef SECCOMP_USER_NOTIF_FLAG_CONTINUE
#define SECCOMP_USER_NOTIF_FLAG_CONTINUE (1UL << 0)
#endif

typedef int (*seccomp_exec_logger_callback)(const char *syscall_name,
                                            const char *path,
                                            char *const argv[],
                                            char *const envp[],
                                            void *user_data);

static void set_error(char *errbuf, size_t errbuf_len, const char *message) {
  if (errbuf && errbuf_len) {
    snprintf(errbuf, errbuf_len, "%s", message ? message : "");
  }
}

static void set_errno_error(char *errbuf, size_t errbuf_len, const char *where) {
  if (errbuf && errbuf_len) {
    snprintf(errbuf, errbuf_len, "%s: %s", where, strerror(errno));
  }
}

static int send_fd(int sock, int fd) {
  char buf[1] = {0};
  struct iovec io = {buf, sizeof(buf)};
  char cmsgbuf[CMSG_SPACE(sizeof(int))];
  memset(cmsgbuf, 0, sizeof(cmsgbuf));
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = &io;
  msg.msg_iovlen = 1;
  msg.msg_control = cmsgbuf;
  msg.msg_controllen = sizeof(cmsgbuf);
  struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
  cmsg->cmsg_level = SOL_SOCKET;
  cmsg->cmsg_type = SCM_RIGHTS;
  cmsg->cmsg_len = CMSG_LEN(sizeof(int));
  memcpy(CMSG_DATA(cmsg), &fd, sizeof(int));
  return sendmsg(sock, &msg, 0) == 1 ? 0 : -1;
}

static int recv_fd(int sock) {
  char buf[1];
  struct iovec io = {buf, sizeof(buf)};
  char cmsgbuf[CMSG_SPACE(sizeof(int))];
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = &io;
  msg.msg_iovlen = 1;
  msg.msg_control = cmsgbuf;
  msg.msg_controllen = sizeof(cmsgbuf);
  if (recvmsg(sock, &msg, 0) <= 0)
    return -1;
  struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
  if (!cmsg || cmsg->cmsg_level != SOL_SOCKET || cmsg->cmsg_type != SCM_RIGHTS)
    return -1;
  int fd = -1;
  memcpy(&fd, CMSG_DATA(cmsg), sizeof(int));
  return fd;
}

static int install_filter(void) {
  struct sock_filter filter[] = {
      BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
      BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 0, 5),
      BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
      BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_execve, 2, 0),
      BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_execveat, 1, 0),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
  };
  struct sock_fprog prog = {
      .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
      .filter = filter};
  if (prctl(PR_SET_DUMPABLE, 1, 0, 0, 0))
    return -1;
  if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
    return -1;
  return (int)syscall(__NR_seccomp, SECCOMP_SET_MODE_FILTER,
                      SECCOMP_FILTER_FLAG_NEW_LISTENER, &prog);
}

static ssize_t read_remote(pid_t pid, unsigned long addr, void *buf, size_t len) {
  struct iovec local = {buf, len};
  struct iovec remote = {(void *)addr, len};
  return process_vm_readv(pid, &local, 1, &remote, 1, 0);
}

static char *read_remote_string(pid_t pid, unsigned long addr) {
  size_t cap = 256, len = 0;
  char *out = malloc(cap);
  if (!out)
    return NULL;
  while (len + 1 < 1048576) {
    char chunk[256];
    ssize_t n = read_remote(pid, addr + len, chunk, sizeof(chunk));
    if (n <= 0)
      break;
    for (ssize_t i = 0; i < n; i++) {
      if (len + 1 >= cap) {
        cap *= 2;
        char *tmp = realloc(out, cap);
        if (!tmp) {
          free(out);
          return NULL;
        }
        out = tmp;
      }
      out[len++] = chunk[i];
      if (chunk[i] == '\0')
        return out;
    }
  }
  out[len < cap ? len : cap - 1] = '\0';
  return out;
}

static char **read_remote_vector(pid_t pid, unsigned long addr) {
  size_t cap = 16, n = 0;
  char **vec = calloc(cap, sizeof(char *));
  if (!vec)
    return NULL;
  for (size_t i = 0; i < 4096; i++) {
    unsigned long ptr = 0;
    if (read_remote(pid, addr + i * sizeof(ptr), &ptr, sizeof(ptr)) !=
        (ssize_t)sizeof(ptr))
      break;
    if (!ptr)
      break;
    if (n + 1 >= cap) {
      cap *= 2;
      char **tmp = realloc(vec, cap * sizeof(char *));
      if (!tmp)
        break;
      vec = tmp;
    }
    vec[n++] = read_remote_string(pid, ptr);
  }
  vec[n] = NULL;
  return vec;
}

static void free_vector(char **v) {
  if (!v)
    return;
  for (size_t i = 0; v[i]; i++)
    free(v[i]);
  free(v);
}

static int handle_notification(int notify_fd, struct seccomp_notif *req,
                               seccomp_exec_logger_callback callback,
                               void *user_data) {
  int is_at = req->data.nr == __NR_execveat;
  unsigned long path_ptr = req->data.args[is_at ? 1 : 0];
  unsigned long argv_ptr = req->data.args[is_at ? 2 : 1];
  unsigned long envp_ptr = req->data.args[is_at ? 3 : 2];
  char *path = read_remote_string(req->pid, path_ptr);
  char **argv = read_remote_vector(req->pid, argv_ptr);
  char **envp = read_remote_vector(req->pid, envp_ptr);
  if (callback) {
    callback(is_at ? "execveat" : "execve", path ? path : "", argv, envp,
             user_data);
  }
  free(path);
  free_vector(argv);
  free_vector(envp);

  struct seccomp_notif_resp resp;
  memset(&resp, 0, sizeof(resp));
  resp.id = req->id;
  resp.val = 0;
  resp.error = 0;
  resp.flags = SECCOMP_USER_NOTIF_FLAG_CONTINUE;
  if (ioctl(notify_fd, SECCOMP_IOCTL_NOTIF_SEND, &resp) < 0 && errno != ENOENT)
    return -1;
  return 0;
}

__attribute__((visibility("default")))
int seccomp_exec_logger_run(int argc, char *const argv[],
                            seccomp_exec_logger_callback callback,
                            void *user_data, char *errbuf,
                            size_t errbuf_len) {
  if (argc < 1 || !argv || !argv[0]) {
    set_error(errbuf, errbuf_len, "missing command");
    return 2;
  }
  int sv[2];
  if (socketpair(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0, sv)) {
    set_errno_error(errbuf, errbuf_len, "socketpair");
    return 1;
  }
  pid_t child = fork();
  if (child < 0) {
    set_errno_error(errbuf, errbuf_len, "fork");
    close(sv[0]);
    close(sv[1]);
    return 1;
  }
  if (child == 0) {
    close(sv[0]);
    int fd = install_filter();
    if (fd < 0)
      _exit(127);
    if (send_fd(sv[1], fd))
      _exit(127);
    close(fd);
    execvp(argv[0], argv);
    _exit(127);
  }

  close(sv[1]);
  int notify_fd = recv_fd(sv[0]);
  close(sv[0]);
  if (notify_fd < 0) {
    set_error(errbuf, errbuf_len, "failed to receive seccomp listener");
    int status;
    waitpid(child, &status, 0);
    return 1;
  }

  for (;;) {
    struct seccomp_notif req;
    memset(&req, 0, sizeof(req));
    if (ioctl(notify_fd, SECCOMP_IOCTL_NOTIF_RECV, &req) < 0) {
      if (errno == EINTR)
        continue;
      break;
    }
    if (handle_notification(notify_fd, &req, callback, user_data) < 0)
      set_errno_error(errbuf, errbuf_len, "notif_send");
  }
  close(notify_fd);

  int status;
  if (waitpid(child, &status, 0) < 0) {
    set_errno_error(errbuf, errbuf_len, "waitpid");
    return 1;
  }
  if (WIFEXITED(status))
    return WEXITSTATUS(status);
  if (WIFSIGNALED(status))
    return 128 + WTERMSIG(status);
  return 1;
}
