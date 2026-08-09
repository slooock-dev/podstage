/* podstage keeper — a persistent, silent uinput pointer device.
 *
 * gamescope's (3.16) Wayland-backend input thread releases its wl_pointer
 * whenever the seat's POINTER capability drops — and Sunshine's virtual
 * devices come and go with every stream, so that happens constantly. The
 * object recreated on the next attach never receives another
 * wl_pointer.enter (wlroots does not replay enter to late-bound resources),
 * after which absolute mouse input is dead for the rest of the session.
 *
 * Keeping one pointer-capable device around for the whole session means the
 * capability never drops and the input thread's wl_pointer survives. The
 * device name matches the host udev rule ("*passthrough*" -> streaming seat
 * + owner chown), and it never emits a single event.
 */
#include <fcntl.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(void) {
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) {
        perror("keeper: /dev/uinput");
        return 1;
    }
    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_KEYBIT, BTN_LEFT);
    ioctl(fd, UI_SET_EVBIT, EV_REL);
    ioctl(fd, UI_SET_RELBIT, REL_X);
    ioctl(fd, UI_SET_RELBIT, REL_Y);

    struct uinput_user_dev dev;
    memset(&dev, 0, sizeof dev);
    strncpy(dev.name, "podstage passthrough keeper", UINPUT_MAX_NAME_SIZE - 1);
    dev.id.bustype = BUS_VIRTUAL;
    dev.id.vendor = 0x1d50;   /* openmoko community space, no real product */
    dev.id.product = 0x0001;
    dev.id.version = 1;
    if (write(fd, &dev, sizeof dev) != (ssize_t)sizeof dev) {
        perror("keeper: write uinput_user_dev");
        return 1;
    }
    if (ioctl(fd, UI_DEV_CREATE) < 0) {
        perror("keeper: UI_DEV_CREATE");
        return 1;
    }
    for (;;)
        pause();   /* the device dies with the process (container stop) */
}
