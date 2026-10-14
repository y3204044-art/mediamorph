package com.mediamorph.studio;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    private static volatile MainActivity instance;

    static MainActivity current() {
        return instance;
    }

    private WebView web;
    private TextView status;
    private boolean starting = false;
    private boolean loaded = false;
    private boolean askedNotifications = false;
    private AlertDialog dialog;

    private static final String HIDE_UNSUPPORTED_JS =
            "(function(){"
                    + "document.querySelectorAll('option[value=\"libsvtav1\"],option[value=\"avif\"]').forEach(function(o){o.remove();});"
                    + "var hw=document.getElementById('cfgHwAccel');"
                    + "if(hw){hw.checked=false;var b=hw.closest('.toggle-banner');if(b){b.style.display='none';}}"
                    + "document.documentElement.classList.add('android');"
                    + "})();";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        instance = this;

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0f172a"));
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                Uri u = request.getUrl();
                if ("127.0.0.1".equals(u.getHost())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                view.evaluateJavascript(HIDE_UNSUPPORTED_JS, null);
                if (status != null) status.setVisibility(android.view.View.GONE);
            }
        });
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        status = new TextView(this);
        status.setText("מכין את המנוע…");
        status.setTextColor(Color.WHITE);
        status.setTextSize(18);
        status.setGravity(Gravity.CENTER);
        root.addView(status, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        checkAndStart();
    }

    private boolean hasStorageAccess() {
        if (Build.VERSION.SDK_INT >= 30) return Environment.isExternalStorageManager();
        return checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
    }

    private void checkAndStart() {
        if (!hasStorageAccess()) {
            askStorageAccess();
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && !askedNotifications
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            askedNotifications = true;
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
        }
        startEngineAndLoad();
    }

    private void askStorageAccess() {
        if (dialog != null && dialog.isShowing()) return;
        status.setText("נדרשת הרשאה לגישה לקבצים");
        if (Build.VERSION.SDK_INT >= 30) {
            dialog = new AlertDialog.Builder(this)
                    .setTitle("גישה לכל הקבצים")
                    .setMessage("כדי לסרוק את המכשיר, להמיר קבצים ולהחליף אותם במקומם, האפליקציה צריכה הרשאת \"גישה לכל הקבצים\". בלחיצה על \"המשך\" תיפתח מסך ההגדרות: הפעילו שם את המתג ואז חזרו לאפליקציה.")
                    .setCancelable(false)
                    .setPositiveButton("המשך", (d, w) -> {
                        try {
                            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                    Uri.parse("package:" + getPackageName())));
                        } catch (Exception e) {
                            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
                        }
                    })
                    .show();
        } else {
            requestPermissions(new String[]{Manifest.permission.READ_EXTERNAL_STORAGE,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE}, 1);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 1) checkAndStart();
    }

    private void startEngineAndLoad() {
        if (loaded || starting) return;
        starting = true;
        status.setText("מכין את המנוע…");
        Intent svc = new Intent(this, ServerService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(svc);
        else startService(svc);

        new Thread(() -> {
            long end = System.currentTimeMillis() + 90_000;
            while (System.currentTimeMillis() < end) {
                if (!ServerService.error.isEmpty()) break;
                int p = ServerService.port;
                if (p > 0 && ServerService.ready && ping(p)) {
                    final int port = p;
                    runOnUiThread(() -> load(port));
                    return;
                }
                try {
                    Thread.sleep(250);
                } catch (InterruptedException ignored) { }
            }
            final String err = ServerService.error.isEmpty() ? "המנוע לא הגיב בזמן" : ServerService.error;
            runOnUiThread(() -> {
                starting = false;
                status.setText("שגיאה בהפעלת המנוע:\n" + err);
            });
        }, "mediamorph-wait").start();
    }

    private boolean ping(int port) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL("http://127.0.0.1:" + port + "/api/status").openConnection();
            c.setConnectTimeout(800);
            c.setReadTimeout(1500);
            c.setRequestProperty("Cookie", "mm_token=" + ServerService.token);
            int code = c.getResponseCode();
            c.disconnect();
            return code == 200;
        } catch (Exception e) {
            return false;
        }
    }

    private void load(int port) {
        loaded = true;
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setCookie("http://127.0.0.1:" + port, "mm_token=" + ServerService.token + "; Path=/");
        cm.flush();
        web.loadUrl("http://127.0.0.1:" + port + "/");
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == AppBridge.REQ_PICK_FOLDER) {
            AppBridge.onPickResult(resultCode == RESULT_OK && data != null ? data.getData() : null);
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else moveTaskToBack(true); // המנוע ממשיך לרוץ ברקע
    }

    @Override
    protected void onDestroy() {
        if (instance == this) instance = null;
        super.onDestroy();
    }
}
