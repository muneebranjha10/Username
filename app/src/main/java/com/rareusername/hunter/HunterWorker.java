package com.rareusername.hunter;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONArray;
import org.json.JSONObject;

public class HunterWorker extends Worker {
    private static final String CHANNEL = "hunter-listing-alerts";
    private static int nextId = 1100;

    public HunterWorker(@NonNull Context ctx, @NonNull WorkerParameters params) {
        super(ctx, params);
    }

    @NonNull @Override public Result doWork() {
        try {
            synchronized (HunterWorker.class) {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                String json = Python.getInstance().getModule("hunter").callAttr("check_once").toString();
                JSONObject value = new JSONObject(json);
                JSONArray alerts = value.optJSONArray("alerts");
                if (alerts != null) {
                    for (int i = 0; i < alerts.length(); i++) {
                        notifyLocal(getApplicationContext(), alerts.optString(i));
                    }
                }
            }
            return Result.success();
        } catch (Exception ex) {
            // Android can retry transient failures, but the Python layer already returns UNKNOWN.
            return Result.retry();
        }
    }

    public static void ensureChannel(Context ctx) {
        NotificationManager manager = (NotificationManager)ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Collectible username alerts",
                    NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Observed Fragment listing changes. Verify before acting.");
            manager.createNotificationChannel(ch);
        }
    }

    public static void notifyLocal(Context ctx, String text) {
        if (Build.VERSION.SDK_INT >= 33 && ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) return;
        ensureChannel(ctx);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(ctx, CHANNEL) : new Notification.Builder(ctx);
        Notification notification = builder
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("Rare Username Hunter")
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text + "\nCheck fragment.com"))
                .setAutoCancel(true)
                .build();
        NotificationManager manager = (NotificationManager)ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        manager.notify(nextId++, notification);
    }
}
