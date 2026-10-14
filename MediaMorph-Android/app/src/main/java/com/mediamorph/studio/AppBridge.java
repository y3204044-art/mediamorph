package com.mediamorph.studio;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.widget.Toast;

import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** פעולות שרק אנדרואיד יכול לבצע; נקראות משרת ה-Python. */
public final class AppBridge {
    static final int REQ_PICK_FOLDER = 4711;
    private static final String EXTERNAL_DOCS = "com.android.externalstorage.documents";

    private static volatile CountDownLatch pickLatch;
    private static volatile String pickResult = "";

    private AppBridge() { }

    /** פותח את בוחר התיקיות של המערכת וממתין לבחירה (עד 5 דקות). מחזיר נתיב או מחרוזת ריקה. */
    public static String pickFolder() {
        final MainActivity a = MainActivity.current();
        if (a == null) return "";
        pickResult = "";
        pickLatch = new CountDownLatch(1);
        a.runOnUiThread(() -> {
            try {
                a.startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), REQ_PICK_FOLDER);
            } catch (ActivityNotFoundException e) {
                pickLatch.countDown();
            }
        });
        try {
            pickLatch.await(5, TimeUnit.MINUTES);
        } catch (InterruptedException ignored) { }
        return pickResult;
    }

    static void onPickResult(Uri tree) {
        pickResult = tree == null ? "" : treeUriToPath(tree);
        CountDownLatch l = pickLatch;
        if (l != null) l.countDown();
    }

    /** ממפה כתובת בוחר תיקיות לנתיב אמיתי (עובד כי לאפליקציה יש גישה לכל הקבצים). */
    static String treeUriToPath(Uri tree) {
        try {
            String docId = DocumentsContract.getTreeDocumentId(tree);
            int i = docId.indexOf(':');
            String vol = i >= 0 ? docId.substring(0, i) : docId;
            String rest = i >= 0 ? docId.substring(i + 1) : "";
            String base = "primary".equals(vol) ? "/storage/emulated/0" : "/storage/" + vol;
            return rest.isEmpty() ? base : base + "/" + rest;
        } catch (Exception e) {
            return "";
        }
    }

    /** "הצג בתיקייה": פותח את התיקייה (או התיקייה של הקובץ) באפליקציית הקבצים. */
    public static boolean reveal(final String path) {
        final MainActivity a = MainActivity.current();
        if (a == null || path == null) return false;
        File f = new File(path);
        final File dir = f.isDirectory() ? f : f.getParentFile();
        if (dir == null) return false;
        final String docId = pathToDocId(dir.getAbsolutePath());
        if (docId == null) return false;
        a.runOnUiThread(() -> {
            try {
                Uri uri = DocumentsContract.buildDocumentUri(EXTERNAL_DOCS, docId);
                Intent i = new Intent(Intent.ACTION_VIEW);
                i.setDataAndType(uri, "vnd.android.document/directory");
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                a.startActivity(i);
            } catch (Exception e) {
                Toast.makeText(a, dir.getAbsolutePath(), Toast.LENGTH_LONG).show();
            }
        });
        return true;
    }

    private static String pathToDocId(String abs) {
        String prim = "/storage/emulated/0";
        if (abs.equals(prim)) return "primary:";
        if (abs.startsWith(prim + "/")) return "primary:" + abs.substring(prim.length() + 1);
        if (abs.startsWith("/storage/")) {
            String rest = abs.substring("/storage/".length());
            int i = rest.indexOf('/');
            if (i < 0) return rest + ":";
            return rest.substring(0, i) + ":" + rest.substring(i + 1);
        }
        return null;
    }
}
