/* podstage pad-bounce: fake an unplug/replug of the connected gamepads.
 *
 * Some games only re-detect their controller after a mid-game re-plug; an
 * additionally hotplugged pad does not trigger them. The streamed pads live
 * on the server process's uinput fd, so destroying them would drop the
 * stream. With the input mirror (input-mirror.c) /dev/input holds symlinks,
 * and removing and restoring a symlink is a real unplug/replug to every
 * consumer (Steam/SDL inotify, the game).
 *
 * Bounced: every event* symlink advertising BTN_GAMEPAD, plus all js*
 * nodes; that covers the server's pad and Steam Input's virtual pad.
 *
 * Exit: 0 bounced, 2 no gamepad connected, 3 mirror inactive.
 *
 * Usage: podstage-pad-bounce [hold_ms]   (default 3000, clamped 100..60000)
 */
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/input.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#define REAL_DIR "/dev/input-real"
#define MIRROR_DIR "/dev/input"
#define MAX_PADS 32

static int has_bit(const unsigned char *bits, unsigned bit) {
    return bits[bit / 8] & (1 << (bit % 8));
}

static int is_gamepad(const char *name) {
    if (strncmp(name, "js", 2) == 0)
        return 1;  /* legacy joystick nodes exist only for pads */
    if (strncmp(name, "event", 5) != 0)
        return 0;
    char path[PATH_MAX];
    snprintf(path, sizeof path, REAL_DIR "/%s", name);
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return 0;
    unsigned char keys[KEY_MAX / 8 + 1] = {0};
    int pad = ioctl(fd, EVIOCGBIT(EV_KEY, sizeof keys), keys) >= 0
              && has_bit(keys, BTN_GAMEPAD);
    close(fd);
    return pad;
}

int main(int argc, char **argv) {
    long hold_ms = 3000;
    if (argc > 1) {
        hold_ms = strtol(argv[1], NULL, 10);
        if (hold_ms < 100)
            hold_ms = 100;
        if (hold_ms > 60000)
            hold_ms = 60000;
    }
    struct stat st;
    if (stat(REAL_DIR, &st) != 0 || !S_ISDIR(st.st_mode)) {
        fprintf(stderr, "input mirror inactive; enable the gamepad_reconnect "
                        "experimental feature and restart the session\n");
        return 3;
    }

    static char pads[MAX_PADS][NAME_MAX + 1];
    int n = 0;
    DIR *d = opendir(MIRROR_DIR);
    if (d == NULL) {
        perror("pad-bounce: " MIRROR_DIR);
        return 1;
    }
    for (struct dirent *e; (e = readdir(d)) != NULL && n < MAX_PADS;) {
        char link[PATH_MAX + NAME_MAX];
        snprintf(link, sizeof link, MIRROR_DIR "/%s", e->d_name);
        if (lstat(link, &st) == 0 && S_ISLNK(st.st_mode) && is_gamepad(e->d_name))
            snprintf(pads[n++], sizeof pads[0], "%s", e->d_name);
    }
    closedir(d);
    if (n == 0) {
        fprintf(stderr, "no gamepad connected\n");
        return 2;
    }

    for (int i = 0; i < n; i++) {
        char link[PATH_MAX + NAME_MAX];
        snprintf(link, sizeof link, MIRROR_DIR "/%.255s", pads[i]);
        unlink(link);
        printf("pad-bounce: %s disconnected\n", pads[i]);
    }
    fflush(stdout);
    usleep((useconds_t)hold_ms * 1000);
    for (int i = 0; i < n; i++) {
        char target[PATH_MAX + NAME_MAX], link[PATH_MAX + NAME_MAX];
        snprintf(target, sizeof target, REAL_DIR "/%.255s", pads[i]);
        snprintf(link, sizeof link, MIRROR_DIR "/%.255s", pads[i]);
        /* The real device can be gone by now (Steam re-creates its virtual
         * pad when the underlying one vanishes); then the node stays gone
         * and the mirror daemon has added the successor already. */
        if (stat(target, &st) == 0 && symlink(target, link) == 0)
            printf("pad-bounce: %s reconnected\n", pads[i]);
    }
    return 0;
}
