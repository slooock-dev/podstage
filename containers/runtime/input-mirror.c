/* podstage input-mirror: /dev/input as a symlink view.
 *
 * With the gamepad_reconnect feature the host runtime mounts the real
 * /dev/input at /dev/input-real and a tmpfs at /dev/input; this daemon
 * mirrors every real device node as a same-named symlink, kept current via
 * inotify. Consumers open the symlinks and never notice the indirection.
 * The point: a symlink can be removed and re-created rootless, which is how
 * pad-bounce fakes an unplug/replug; the real nodes live in the host
 * devtmpfs, out of rootless reach.
 *
 * If this process dies, new devices silently stop reaching the session
 * (open fds keep working); the entrypoint supervises it. Directories
 * (by-id/, by-path/) are not mirrored; nothing in the container reads them.
 *
 * Usage: podstage-input-mirror <real-dir> <mirror-dir>
 */
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *real_dir, *mirror_dir;

static void link_node(const char *name) {
    char target[PATH_MAX], link[PATH_MAX];
    snprintf(target, sizeof target, "%s/%s", real_dir, name);
    snprintf(link, sizeof link, "%s/%s", mirror_dir, name);
    struct stat st;
    if (lstat(target, &st) != 0 || S_ISDIR(st.st_mode))
        return;
    unlink(link);  /* replace a stale/dangling link from an earlier device */
    if (symlink(target, link) != 0 && errno != EEXIST)
        perror("input-mirror: symlink");
}

static void unlink_node(const char *name) {
    char link[PATH_MAX];
    snprintf(link, sizeof link, "%s/%s", mirror_dir, name);
    unlink(link);
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: podstage-input-mirror <real-dir> <mirror-dir>\n");
        return 1;
    }
    real_dir = argv[1];
    mirror_dir = argv[2];

    int ifd = inotify_init1(IN_CLOEXEC);
    if (ifd < 0 || inotify_add_watch(ifd, real_dir,
            IN_CREATE | IN_DELETE | IN_MOVED_TO | IN_MOVED_FROM | IN_ATTRIB) < 0) {
        perror("input-mirror: inotify");
        return 1;
    }
    /* Watch first, then scan: a device appearing between scan and watch
     * would otherwise be missed forever. */
    DIR *d = opendir(real_dir);
    if (d == NULL) {
        perror("input-mirror: real dir");
        return 1;
    }
    for (struct dirent *e; (e = readdir(d)) != NULL;)
        if (e->d_name[0] != '.')
            link_node(e->d_name);
    closedir(d);

    char buf[4096] __attribute__((aligned(__alignof__(struct inotify_event))));
    for (;;) {
        ssize_t len = read(ifd, buf, sizeof buf);
        if (len <= 0) {
            if (errno == EINTR)
                continue;
            perror("input-mirror: read");
            return 1;
        }
        for (char *p = buf; p < buf + len;) {
            struct inotify_event *ev = (struct inotify_event *)p;
            p += sizeof *ev + ev->len;
            if (ev->len == 0 || ev->name[0] == '.' || (ev->mask & IN_ISDIR))
                continue;
            if (ev->mask & (IN_DELETE | IN_MOVED_FROM))
                unlink_node(ev->name);
            else
                link_node(ev->name);
        }
    }
}
