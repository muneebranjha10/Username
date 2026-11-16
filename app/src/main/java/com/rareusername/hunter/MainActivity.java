package com.rareusername.hunter;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class MainActivity extends Activity {
    private final int bg = Color.rgb(9, 13, 25);
    private final int panel = Color.rgb(21, 29, 46);
    private final int accent = Color.rgb(66, 211, 228);
    private final int pale = Color.rgb(199, 209, 224);
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private EditText apiId, apiHash, phone, code, password, name;
    private TextView status, watched, suggestions;
    private LinearLayout root;

    interface OnResult { void complete(JSONObject result); }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(bg);
        getWindow().setNavigationBarColor(bg);
        HunterWorker.ensureChannel(this);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 23);
        }
        buildUi();
        refresh();
    }

    private GradientDrawable background(int color) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(15));
        return d;
    }
    private int dp(int n) { return (int)(getResources().getDisplayMetrics().density*n + .5f); }
    private LinearLayout.LayoutParams margins() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2);
        p.setMargins(0, dp(6), 0, dp(8));
        return p;
    }
    private TextView text(String label, int size, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(label); v.setTextSize(size); v.setTextColor(color);
        if (bold) v.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        v.setPadding(dp(4), dp(6), dp(4), dp(6));
        return v;
    }
    private void heading(String title) {
        TextView v = text(title, 19, Color.WHITE, true);
        v.setPadding(dp(4), dp(18), dp(4), dp(8));
        root.addView(v);
    }
    private EditText edit(String hint, int type) {
        EditText v = new EditText(this);
        v.setHint(hint); v.setHintTextColor(Color.rgb(135, 149, 170));
        v.setSingleLine(true); v.setTextColor(Color.WHITE); v.setTextSize(15);
        v.setInputType(type);
        v.setBackground(background(panel)); v.setPadding(dp(14), dp(11), dp(14), dp(11));
        root.addView(v, margins());
        return v;
    }
    private void button(String label, Runnable click, boolean primary) {
        Button v = new Button(this);
        v.setText(label); v.setAllCaps(false); v.setTextSize(14);
        v.setTextColor(primary ? bg : Color.WHITE);
        v.setBackground(background(primary ? accent : panel));
        v.setOnClickListener(x -> click.run());
        root.addView(v, margins());
    }
    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true); scroll.setBackgroundColor(bg);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(36));
        scroll.addView(root); setContentView(scroll);
        root.addView(text("◈  RARE USERNAME HUNTER", 24, accent, true));
        root.addView(text("4-letter collectibles  ·  Private device session", 13, pale, false));
        status = text("Loading…", 14, pale, false);
        status.setBackground(background(panel)); status.setPadding(dp(14), dp(12), dp(14), dp(12));
        root.addView(status, margins());
        heading("01  Connect Telegram");
        root.addView(text("Get your API ID + hash at my.telegram.org. Login codes and 2-step passwords stay on your device.", 13, pale, false));
        apiId = edit("Telegram API ID", InputType.TYPE_CLASS_NUMBER);
        apiHash = edit("Telegram API hash (32 characters)", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        phone = edit("Phone including country code (+92...)", InputType.TYPE_CLASS_PHONE);
        button("Send Telegram login code", () -> runPython("begin_login", obj -> showResult(obj),
                apiId.getText().toString(), apiHash.getText().toString(), phone.getText().toString()), true);
        code = edit("Verification code", InputType.TYPE_CLASS_NUMBER);
        button("Verify code", () -> runPython("verify_code", this::showResult, code.getText().toString()), false);
        password = edit("2-step password (only if asked)", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        button("Verify 2-step password", () -> runPython("verify_password", obj -> {
            password.setText(""); showResult(obj);
        }, password.getText().toString()), false);
        button("Send test alert to Saved Messages", () -> runPython("test_alert", this::showResult), false);

        heading("02  Four-character watchlist");
        root.addView(text("Only public Fragment listings are checked. Unknown is NOT available. Add max 20 names; five checked each cycle.", 13, pale, false));
        name = edit("e.g. zova", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        button("Add to watchlist", () -> runPython("add", obj -> { showResult(obj); refresh(); }, name.getText().toString()), true);
        button("Remove from watchlist", () -> runPython("remove", obj -> { showResult(obj); refresh(); }, name.getText().toString()), false);
        button("Open this name on official Fragment", this::openFragment, false);
        watched = text("No names added yet.", 14, pale, false);
        watched.setPadding(dp(12), dp(12), dp(12), dp(12)); watched.setBackground(background(panel));
        root.addView(watched, margins());
        button("Refresh watchlist", this::refresh, false);

        heading("03  Safe monitoring & alerts");
        root.addView(text("30-minute Android background job; actual timing is controlled by Android battery optimization. Only verified state changes or observed price drops trigger alerts.", 13, pale, false));
        button("Check now (up to 5 names)", () -> runPython("check_once", result -> {
            showResult(result); notifyAlerts(result); refresh();
        }), true);
        button("Start scheduled checks", this::startMonitor, false);
        button("Stop scheduled checks", () -> {
            WorkManager.getInstance(this).cancelUniqueWork("fragment-monitor");
            status.setText("Scheduled checks canceled.");
        }, false);

        heading("04  Username ideas");
        root.addView(text("Pronounceable suggestions only — NOT checked, free, or guaranteed valuable.", 13, pale, false));
        button("Generate 12 ideas", () -> runPython("suggest", result -> {
            JSONArray a = result.optJSONArray("suggestions");
            if (a != null) {
                StringBuilder s = new StringBuilder();
                for (int i = 0; i < a.length(); i++) s.append('@').append(a.optString(i)).append(i == a.length()-1 ? "" : "    ");
                suggestions.setText(s.toString());
            }
        }), false);
        suggestions = text("", 15, accent, false);
        root.addView(suggestions);

        heading("05  Session & safety");
        root.addView(text("App-private session is powerful: never share APK data, API hash, .session files, login codes or passwords. Only buy through the real fragment.com in a trusted browser.", 13, pale, false));
        button("Sign out / delete local Telegram session", () -> runPython("sign_out", obj -> {
            showResult(obj); refresh();
        }), false);
        root.addView(text("Research tool only. No bidding, purchases, wallet connection, reclaim attempts, bulk username claiming, or guaranteed profit.", 12, pale, false));
    }

    private void runPython(String method, OnResult callback, String... args) {
        status.setText("Working: " + method + " …");
        executor.execute(() -> {
            JSONObject out;
            try {
                PyObject module = Python.getInstance().getModule("hunter");
                PyObject obj = module.callAttr(method, (Object[]) args);
                out = new JSONObject(obj.toString());
            } catch (Exception ex) {
                out = new JSONObject();
                try {
                    out.put("ok", false);
                    out.put("message", "Operation failed: " + ex.getClass().getSimpleName());
                } catch (Exception ignored) { }
            }
            JSONObject safe = out;
            ui.post(() -> callback.complete(safe));
        });
    }
    private void showResult(JSONObject data) {
        String msg = data.optString("message", "Done.");
        JSONArray checked = data.optJSONArray("checked");
        if (checked != null) {
            StringBuilder sb = new StringBuilder(msg).append("\n");
            for (int i = 0; i < checked.length(); i++) sb.append("\n").append(checked.optString(i));
            msg = sb.toString();
        }
        status.setText(msg);
    }
    private void refresh() {
        runPython("snapshot", data -> {
            JSONArray names = data.optJSONArray("watch");
            JSONObject results = data.optJSONObject("results");
            StringBuilder b = new StringBuilder("WATCHLIST\n");
            if (names != null && names.length() > 0) {
                for (int i = 0; i < names.length(); i++) {
                    String n = names.optString(i);
                    JSONObject result = results == null ? null : results.optJSONObject(n);
                    b.append('\n').append('@').append(n).append("   ·   ");
                    b.append(result == null ? "NOT CHECKED" : result.optString("state", "UNKNOWN"));
                    if (result != null && result.has("price") && !result.optString("state").equals("UNKNOWN")) {
                        b.append("   ·   ").append(result.optString("price"))
                                .append(' ').append(result.optString("currency"));
                    }
                }
            } else b.append("\nNo watched names yet.");
            b.append("\n\nTelegram: ").append(data.optString("login_hint", "Not configured"));
            b.append("\nLast check: ").append(data.optString("last_check", "Never"));
            watched.setText(b.toString());
            status.setText("Ready. Fragment listings are never guaranteed.");
        });
    }
    private void openFragment() {
        String n = name.getText().toString().trim().toLowerCase(java.util.Locale.ROOT).replace("@", "");
        if (!n.matches("[a-z]{4}")) {
            status.setText("Enter a 4-character name first.");
            return;
        }
        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://fragment.com/username/" + n)));
    }
    private void startMonitor() {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED).build();
        PeriodicWorkRequest task = new PeriodicWorkRequest.Builder(
                HunterWorker.class, 30, TimeUnit.MINUTES).setConstraints(constraints).build();
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                "fragment-monitor", ExistingPeriodicWorkPolicy.UPDATE, task);
        status.setText("Monitoring scheduled every ~30 minutes. Android may delay checks to save battery.");
    }
    private void notifyAlerts(JSONObject result) {
        JSONArray alerts = result.optJSONArray("alerts");
        if (alerts == null) return;
        for (int i=0; i<alerts.length(); i++) HunterWorker.notifyLocal(this, alerts.optString(i));
    }
    @Override protected void onDestroy() {
        executor.shutdown();
        super.onDestroy();
    }
}
