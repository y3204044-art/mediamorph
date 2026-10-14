package com.mediamorph.studio;

import com.arthenica.ffmpegkit.FFmpegKit;
import com.arthenica.ffmpegkit.FFmpegSession;
import com.arthenica.ffmpegkit.FFprobeKit;
import com.arthenica.ffmpegkit.MediaInformation;
import com.arthenica.ffmpegkit.MediaInformationSession;
import com.arthenica.ffmpegkit.ReturnCode;
import com.arthenica.ffmpegkit.Statistics;

import java.util.Locale;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * גשר בין שרת ה-Python ל-FFmpeg. מופעל מ-Python דרך Chaquopy (פונקציות סטטיות פשוטות).
 * ההתקדמות מוחזרת בפורמט שורות "מפתח=ערך", כמו הפלט של ffmpeg -progress, כדי ששרת ה-Python יישאר כמעט ללא שינוי.
 */
public final class FfBridge {
    private static final AtomicInteger IDS = new AtomicInteger(1);
    private static final ConcurrentHashMap<Integer, Job> JOBS = new ConcurrentHashMap<>();
    public static final String DONE = "\u0000DONE";

    private static final class Job {
        final ConcurrentLinkedQueue<String> lines = new ConcurrentLinkedQueue<>();
        volatile boolean done = false;
        volatile int rc = -1;
        volatile long sessionId = 0;
    }

    private FfBridge() { }

    /** קריאת נתוני מדיה כ-JSON (בפורמט ffprobe). מחזיר מחרוזת ריקה בכישלון. */
    public static String probeJson(String path, int timeoutMs) {
        final CountDownLatch latch = new CountDownLatch(1);
        final MediaInformationSession session = FFprobeKit.getMediaInformationAsync(path, s -> latch.countDown());
        try {
            if (!latch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                FFmpegKit.cancel(session.getSessionId());
                return "";
            }
        } catch (InterruptedException e) {
            FFmpegKit.cancel(session.getSessionId());
            return "";
        }
        MediaInformation info = session.getMediaInformation();
        if (info == null || info.getAllProperties() == null) return "";
        return info.getAllProperties().toString();
    }

    /** הרצה סינכרונית של ffmpeg. מחזיר "RC:<קוד>\n<פלט>" או "RC:TIMEOUT\n". */
    public static String runSync(String[] args, int timeoutMs) {
        final CountDownLatch latch = new CountDownLatch(1);
        final FFmpegSession session = FFmpegKit.executeWithArgumentsAsync(args, s -> latch.countDown());
        try {
            if (!latch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                FFmpegKit.cancel(session.getSessionId());
                return "RC:TIMEOUT\n";
            }
        } catch (InterruptedException e) {
            FFmpegKit.cancel(session.getSessionId());
            return "RC:TIMEOUT\n";
        }
        ReturnCode rc = session.getReturnCode();
        int code = rc == null ? -1 : rc.getValue();
        String out = session.getOutput();
        return "RC:" + code + "\n" + (out == null ? "" : out);
    }

    /** התחלת המרה ברקע. מחזיר מזהה לעבודה. */
    public static int start(String[] args) {
        final int id = IDS.getAndIncrement();
        final Job job = new Job();
        JOBS.put(id, job);
        FFmpegSession session = FFmpegKit.executeWithArgumentsAsync(
                args,
                s -> {
                    ReturnCode rc = s.getReturnCode();
                    job.rc = rc == null ? -1 : rc.getValue();
                    job.done = true;
                },
                log -> { },
                st -> job.lines.add(progressLines(st)));
        job.sessionId = session.getSessionId();
        return id;
    }

    private static String progressLines(Statistics st) {
        long ms = (long) st.getTime();
        StringBuilder sb = new StringBuilder();
        sb.append("frame=").append(Math.max(0, st.getVideoFrameNumber())).append('\n');
        sb.append("fps=").append(String.format(Locale.US, "%.1f", st.getVideoFps())).append('\n');
        sb.append("bitrate=").append(String.format(Locale.US, "%.1fkbits/s", st.getBitrate())).append('\n');
        if (st.getSize() >= 0) sb.append("total_size=").append(st.getSize()).append('\n');
        if (ms >= 0) {
            sb.append("out_time_us=").append(ms * 1000L).append('\n');
            long totalSec = ms / 1000L;
            sb.append(String.format(Locale.US, "out_time=%02d:%02d:%02d.%02d\n",
                    totalSec / 3600, (totalSec % 3600) / 60, totalSec % 60, (ms % 1000L) / 10L));
        }
        sb.append("speed=").append(String.format(Locale.US, "%.2fx", st.getSpeed())).append('\n');
        return sb.toString();
    }

    /** שורות התקדמות שהצטברו. מחרוזת ריקה = אין חדש. DONE = העבודה הסתיימה והכול נקרא. */
    public static String poll(int id) {
        Job job = JOBS.get(id);
        if (job == null) return DONE;
        StringBuilder sb = new StringBuilder();
        String l;
        while ((l = job.lines.poll()) != null) sb.append(l);
        if (sb.length() > 0) return sb.toString();
        return job.done ? DONE : "";
    }

    public static boolean isDone(int id) {
        Job job = JOBS.get(id);
        return job == null || job.done;
    }

    public static int returnCode(int id) {
        Job job = JOBS.get(id);
        return job == null ? -1 : job.rc;
    }

    public static void cancel(int id) {
        Job job = JOBS.get(id);
        if (job == null) return;
        if (job.sessionId != 0) FFmpegKit.cancel(job.sessionId);
        else FFmpegKit.cancel();
    }

    public static void release(int id) {
        JOBS.remove(id);
    }
}
