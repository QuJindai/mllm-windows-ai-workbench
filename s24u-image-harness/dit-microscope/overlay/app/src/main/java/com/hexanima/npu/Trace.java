package com.hexanima.npu;

import android.content.Context;
import java.io.*;
import java.nio.*;
import java.nio.file.Files;
import org.json.*;

/** Observes existing preview buffers and UI events. Never starts an inference. */
final class Trace {
    static File current; static JSONObject state; static long started; static volatile boolean active;
    static synchronized void begin(Context cx,String id,String name,String prompt,String seed,int w,int h,int steps,long t0) {
        try {
            File root=new File(cx.getFilesDir(),"dit_microscope");root.mkdirs();
            current=new File(root,Long.toString(System.currentTimeMillis()));current.mkdirs();started=System.currentTimeMillis();active=true;
            state=new JSONObject().put("id",id).put("model",name).put("prompt",prompt).put("seed",seed).put("width",w).put("height",h).put("steps",steps)
                .put("started",started).put("status","running").put("events",new JSONArray()).put("frames",new JSONArray())
                .put("notice","采集原引擎已有的逐步 x0 估计；不是 attention，也不是额外 VAE 解码。轮询可能跳过快速步骤。阶段事件为界面观测时间，实际内核耗时以日志为准。");
            Files.writeString(new File(root,"latest").toPath(),current.getName());save();
        } catch(Exception ignored) { active=false; }
    }
    static synchronized void progress(Context cx,int pct,String msg) {
        if(!active||state==null)return;
        try { JSONArray a=state.getJSONArray("events");if(a.length()>0&&a.getJSONObject(a.length()-1).optString("label").equals(msg))return;
            if(a.length()<512)a.put(new JSONObject().put("ms",System.currentTimeMillis()-started).put("percent",pct).put("label",msg));save();
        }catch(Exception ignored){}
    }
    static synchronized void capture(byte[] raw,int h,int w,int c,int step) {
        if(!active||state==null||h<=0||w<=0||c<=0||raw.length!=16L+4L*h*w*c||raw.length>32*1024*1024)return;
        try { JSONArray a=state.getJSONArray("frames");for(int i=0;i<a.length();i++)if(a.getJSONObject(i).getInt("step")==step)return;
            long bytes=state.optLong("frame_bytes");if(a.length()>=32||bytes+raw.length>128L*1024*1024){state.put("capture_limit",true);save();return;}
            String file="x0_"+step+".bin";Files.write(new File(current,file).toPath(),raw);
            a.put(new JSONObject().put("step",step).put("h",h).put("w",w).put("c",c).put("file",file).put("ms",System.currentTimeMillis()-started));
            state.put("frame_bytes",bytes+raw.length);save();
        }catch(Exception ignored){}
    }
    static synchronized void finish(Context cx,boolean ok,boolean cancelled) {
        if(state==null)return;
        try {if(ok&&!cancelled)captureFinal(cx);state.put("status",cancelled?"cancelled":ok?"complete":"failed").put("total_ms",System.currentTimeMillis()-started);
            String dir=family(state.optString("id"));File base=new File(cx.getFilesDir(),dir);
            String log=dir.equals("anima")?"animad.log":dir+".log";
            for(String n:new String[]{log,"ids.i32"}) {File f=new File(base,n);if(f.isFile())Files.copy(f.toPath(),new File(current,n).toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);}
            save();active=false;
        }catch(Exception ignored){active=false;}
    }
    static void captureFinal(Context cx) {
        String fam=family(state.optString("id"));
        if(!fam.equals("qwen")&&!fam.equals("moss")&&!fam.equals("klein"))return;
        try {
            int div=fam.equals("moss")?8:16,c=fam.equals("moss")?32:fam.equals("qwen")?64:128;
            int h=state.getInt("height")/div,w=state.getInt("width")/div,step=state.getInt("steps")-1;
            File f=new File(new File(cx.getFilesDir(),fam),fam.equals("klein")?"z.f32":"z.raw");
            long expected=4L*h*w*c;if(f.length()!=expected||expected>32L*1024*1024-16)throw new IOException("final latent size mismatch");
            byte[] raw=FinalLatent.wrap(Files.readAllBytes(f.toPath()),h,w,c,step,fam.equals("klein"));
            capture(raw,h,w,c,step);
            JSONArray a=state.getJSONArray("frames");boolean captured=false;for(int i=0;i<a.length();i++)if(a.getJSONObject(i).getInt("step")==step){
                a.getJSONObject(i).put("source","final_latent").put("source_file",fam+"/"+f.getName());captured=true;}
            state.put("final_capture",captured?"captured":"capture_limit");
        }catch(Exception e){try{state.put("final_capture","failed: "+e.getMessage());}catch(Exception ignored){}}
    }
    static String family(String id){return id.startsWith("qwen")?"qwen":id.startsWith("moss")?"moss":id.startsWith("flux")?"klein":id.startsWith("mage")?"mage":"anima";}
    static void save() throws Exception {File tmp=new File(current,"trace.tmp");Files.writeString(tmp.toPath(),state.toString());Files.move(tmp.toPath(),new File(current,"trace.json").toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);}
    static JSONObject readTrace(File dir) throws Exception {
        return new JSONObject(Files.readString(new File(dir,"trace.json").toPath()));
    }
    static File latest(Context cx, String model) throws IOException {
        File root = new File(cx.getFilesDir(), "dit_microscope");
        File[] dirs = root.listFiles(f -> f.isDirectory() && f.getName().matches("[0-9]{13}"));
        if (dirs != null && model != null) {
            java.util.Arrays.sort(dirs, java.util.Comparator.comparing(File::getName).reversed());
            for (File dir : dirs) {
                try { if (model.equals(readTrace(dir).optString("id"))) return dir; }
                catch (Exception ignored) { }
            }
        }
        throw new IOException("no trace for selected model");
    }
    static synchronized String snapshot(Context cx, String model, String name) {
        try {File d=latest(cx,model);JSONObject o=readTrace(d).put("run",d.getName());
            String family=family(o.optString("id"));File live=new File(cx.getFilesDir(),family);boolean running=o.optString("status").equals("running")&&active;
            File source=running?live:d;String log=family.equals("anima")?"animad.log":family+".log";File lf=new File(source,log);
            if(lf.isFile())try(RandomAccessFile r=new RandomAccessFile(lf,"r")){long start=Math.max(0,r.length()-128*1024);r.seek(start);byte[] b=new byte[(int)(r.length()-start)];r.readFully(b);o.put("log",new String(b,java.nio.charset.StandardCharsets.UTF_8));}
            File ids=new File(source,"ids.i32");if(ids.isFile()&&ids.length()<=65536){byte[] b=Files.readAllBytes(ids.toPath());IntBuffer ints=ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).asIntBuffer();JSONArray a=new JSONArray();while(ints.hasRemaining())a.put(ints.get());o.put("token_ids",a);}
            o.put("backend",family.equals("anima")?"DiT：Hexagon HMX / NPU；其他阶段以实际原生日志为准":"文本编码 / DiT / VAE：原生 Hexagon NPU 配置；执行证据见日志");
            return o.toString();
        }catch(Exception e){
            return "{\"status\":\"idle\",\"notice\":" + JSONObject.quote(name + " · 暂无生成记录") + "}";
        }
    }
    private static String scaleKey;
    private static double scale;
    private static double channelScale(File dir, JSONArray frames, int channel) throws Exception {
        String key = dir.getPath() + ":" + channel + ":" + frames.toString();
        if (key.equals(scaleKey)) return scale;
        double bound = 0;
        for (int i = 0; i < frames.length(); i++) {
            JSONObject frame = frames.getJSONObject(i);
            if (channel >= frame.getInt("c")) continue;
            int count = frame.getInt("w") * frame.getInt("h");
            try (RandomAccessFile file = new RandomAccessFile(new File(dir, frame.getString("file")), "r")) {
                byte[] samples = new byte[count * 4];
                file.seek(16L + (long) channel * samples.length);
                file.readFully(samples);
                FloatBuffer values = ByteBuffer.wrap(samples).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
                while (values.hasRemaining()) {
                    float value = values.get();
                    if (Float.isFinite(value)) bound = Math.max(bound, Math.abs(value));
                }
            }
        }
        scale = bound;
        scaleKey = key;
        return scale;
    }
    static synchronized String frame(Context cx,String model,String run,int index,int channel) {
        try {
            if (!run.matches("[0-9]{13}")) return "{}";
            File d = new File(new File(cx.getFilesDir(),"dit_microscope"),run);
            JSONObject o = readTrace(d);
            if (!o.optString("id").equals(model)) return "{}";
            JSONArray frames = o.getJSONArray("frames");
            JSONObject f = frames.getJSONObject(index);
            byte[] raw=Files.readAllBytes(new File(d,f.getString("file")).toPath());ByteBuffer b=ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);int h=b.getInt(),w=b.getInt(),c=b.getInt(),step=b.getInt();if(channel<0||channel>=c)throw new IOException();
            FloatBuffer z=b.asFloatBuffer();int n=h*w;ChannelStats stats=new ChannelStats(z,channel*n,n);
            int stride=Math.max(1,(int)Math.ceil(Math.max(w,h)/96.0));JSONArray pixels=new JSONArray();for(int y=0;y<h;y+=stride)for(int x=0;x<w;x+=stride){float v=z.get(channel*n+y*w+x);pixels.put(Float.isFinite(v)?v:JSONObject.NULL);}
            return new JSONObject().put("w",(w+stride-1)/stride).put("h",(h+stride-1)/stride).put("source_w",w).put("source_h",h).put("channel",channel).put("step",step).put("min",stats.min).put("max",stats.max).put("mean",stats.mean).put("std",stats.std).put("nonfinite",stats.nonfinite).put("scale",channelScale(d,frames,channel)).put("pixels",pixels).toString();
        }catch(Exception e){return "{}";}
    }
}
