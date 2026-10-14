package com.mediamorph.studio;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.content.res.AssetManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.ServerSocket;
import java.security.SecureRandom;

/** מריץ את מנוע MediaMorph (Python) כשירות קדמי, כדי שהמרות ימשיכו גם כשהמסך כבוי. */
public class ServerService extends Service {
    static final String ACTION_STOP = "com.mediamorph.studio.STOP";
    private static final String CHANNEL = "mediamorph_engine";

    static volatile int port = 0;
    static volatile String token = "";
    static volatile boolean ready = false;
    static volatile String error = "";

    private PowerManager.WakeLock wakeLock;
    private boolean started = false;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopForeground(true);
            stopSelf();
            android.os.Process.killProcess(android.os.Process.myPid());
            return START_NOT_STICKY;
        }
        goForeground();
        if (!started) {
            started = true;
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MediaMorph:engine");
            wakeLock.acquire(6L * 60 * 60 * 1000);
            new Thread(this::runEngine, "mediamorph-engine").start();
        }
        return START_STICKY;
    }

    private void goForeground() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "MediaMorph", NotificationManager.IMPORTANCE_LOW));
        }
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent openPi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE);
        Intent stop = new Intent(this, ServerService.class).setAction(ACTION_STOP);
        PendingIntent stopPi = PendingIntent.getService(this, 1, stop, PendingIntent.FLAG_IMMUTABLE);

        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("MediaMorph פועל ברקע")
                .setContentText("המרות וסריקות ממשיכות גם כשהמסך כבוי")
                .setContentIntent(openPi)
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "עצירה ויציאה", stopPi).build());
        Notification n = b.build();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(1, n);
        }
    }

    private void runEngine() {
        try {
            File uiDir = new File(getFilesDir(), "ui");
            copyAssets(getAssets(), "ui", uiDir);

            byte[] raw = new byte[24];
            new SecureRandom().nextBytes(raw);
            StringBuilder sb = new StringBuilder();
            for (byte x : raw) sb.append(String.format("%02x", x));
            token = sb.toString();

            int p;
            try (ServerSocket s = new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))) {
                p = s.getLocalPort();
            }
            port = p;

            Python py = Python.getInstance();
            PyObject environ = py.getModule("os").get("environ");
            environ.callAttr("__setitem__", "MEDIAMORPH_UI_DIR", uiDir.getAbsolutePath());
            environ.callAttr("__setitem__", "MEDIAMORPH_TOKEN", token);
            PyObject server = py.getModule("server");
            ready = true;
            server.callAttr("start_server", p); // חוסם לצמיתות
        } catch (Throwable t) {
            error = String.valueOf(t);
        }
    }

    private static void copyAssets(AssetManager am, String assetDir, File outDir) throws IOException {
        String[] names = am.list(assetDir);
        if (names == null) return;
        //noinspection ResultOfMethodCallIgnored
        outDir.mkdirs();
        for (String name : names) {
            String child = assetDir + "/" + name;
            String[] sub = am.list(child);
            if (sub != null && sub.length > 0) {
                copyAssets(am, child, new File(outDir, name));
            } else {
                try (InputStream in = am.open(child); FileOutputStream out = new FileOutputStream(new File(outDir, name))) {
                    byte[] buf = new byte[64 * 1024];
                    int n;
                    while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                }
            }
        }
    }

    @Override
    public void onDestroy() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }
}
