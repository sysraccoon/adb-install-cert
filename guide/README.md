# Manual certificate installation to Android system store (**root required!**)

Automated solution [described here](https://github.com/sysraccoon/adb-install-cert).
Below I describe manual steps that reproduce application inner logic.

## Generate new pem certificate (skip if already exists)

Demo:\
![demo-cert-gen](./demo-cert-gen.gif)

```sh
$ openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout key.pem -out cert.pem
```

> [!TIP]
> For [mitmproxy](https://github.com/mitmproxy/mitmproxy) you can use certificate from `~/.mitmproxy/mitmproxy-ca-cert.pem`\
> If you want generate new certificate add extensions `critical` and `keyCertSign` as [described here](https://docs.mitmproxy.org/stable/concepts-certificates/#using-a-custom-certificate-authority):
> ```sh
> openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout key.pem -out cert.pem -addext keyUsage=critical,keyCertSign
> cat key.pem cert.pem > mitmproxy-ca.pem
> mitmproxy --set confdir=$(pwd)
> ```

## Prepare certificate

Demo:\
![demo-prep-cert](./demo-prep-cert.gif)

Android work with PEM certificates that named as `$hash.0` where `$hash` is md5 based hash that can be generate via openssl with `-subject_hash_old` option:

```sh
$ openssl x509 -inform PEM -subject_hash_old -noout -in cert.pem
e210c8c4
$ cp cert.pem e210c8c4.0
```

All certificates in system store also contains additional information. SSL would work without that, but for consistency we can add it to our file:

```sh
$ openssl x509 -inform PEM -text -fingerprint -noout -in cert.pem >> e210c8c4.0
```

Push prepared certificate somewhere on android device

```sh
$ adb push e210c8c4.0 /data/local/tmp/e210c8c4.0
```

## Permanent certificate installation (Android 9 or older)

Before Android 10, permanent installation of a certificate is possible by remounting the root directory in read-write mode. **These changes may require a device reboot**.

```sh
$ adb shell su

mount -o rw,remount,rw /system # or '/' itself
mv /data/local/tmp/e210c8c4.0 /system/etc/security/cacerts/
chmod 644 /system/etc/security/cacerts/
mount -o ro,remount,ro /system # or '/' itself
reboot
```

## Temporary certificate installation (Android 10-13)

Starting with Android 10, the root system is available in read-only mode. To install a certificate, need remounting `/system/etc/security/cacerts` directory in `tmpfs` with a preliminary copy of all existing certificates. **After a reboot, the changes will be reset**.

```sh
$ adb shell su

mkdir -p -m 700 /data/local/tmp/cacerts
cp /system/etc/security/cacerts/* /data/local/tmp/cacerts/
mount -t tmpfs tmpfs /system/etc/security/cacerts/
cp /data/local/tmp/cacerts/* /system/etc/security/cacerts/
mv /data/local/tmp/e210c8c4.0 /system/etc/security/cacerts/
chmod 644 /system/etc/security/cacerts/e210c8c4.0
chcon u:object_r:system_file:s0 /system/etc/security/cacerts/*
```

## Temporary certificate installation (Android 14 or newer)

[Original post](https://httptoolkit.com/blog/android-14-install-system-ca-certificate/)

Starting with Android 14, all certificates available in `/apex/com.android.conscrypt/cacerts`, but this folder is available in read-only mode. Remounting them as `tmpfs` don't actually work. We should change filesystem inside zygote (and zygote childs) namespace.

Do same steps as for Android 10, but copy certs from `/apex/com.android.conscrypt/cacerts/*` instead of `/system/etc/security/cacerts/*`

![demo-android-14](./demo-android-14.gif)

```sh
$ adb shell su

mkdir -p -m 700 /data/local/tmp/cacerts
cp /apex/com.android.conscrypt/cacerts/* /data/local/tmp/cacerts/
mount -t tmpfs tmpfs /system/etc/security/cacerts/
cp /data/local/tmp/cacerts/* /system/etc/security/cacerts/
mv /data/local/tmp/e210c8c4.0 /system/etc/security/cacerts/
chmod 644 /system/etc/security/cacerts/e210c8c4.0
chcon u:object_r:system_file:s0 /system/etc/security/cacerts/*
```

Perform bind mount inside zygote (and child) processes

![demo-android-14-conscrypt](./demo-android-14-conscrypt.gif)
```sh
$ adb shell su

ZYGOTE_PID=$(pidof zygote || true)
ZYGOTE64_PID=$(pidof zygote64 || true)
for Z_PID in "$ZYGOTE_PID" "$ZYGOTE64_PID"; do
    if [ -n "$Z_PID" ]; then
        nsenter --mount=/proc/$Z_PID/ns/mnt -- \
            /bin/mount --bind /system/etc/security/cacerts /apex/com.android.conscrypt/cacerts
    fi
done
APP_PIDS=$(
    echo "$ZYGOTE_PID $ZYGOTE64_PID" | \
    xargs -n1 ps -o 'PID' -P | \
    grep -v PID
)
for PID in $APP_PIDS; do
    nsenter --mount=/proc/$PID/ns/mnt -- \
        /bin/mount --bind /system/etc/security/cacerts /apex/com.android.conscrypt/cacerts &
done
wait
```

Result:

![android-14-trusted-store-demo](./android-14-trusted-store-demo.gif)