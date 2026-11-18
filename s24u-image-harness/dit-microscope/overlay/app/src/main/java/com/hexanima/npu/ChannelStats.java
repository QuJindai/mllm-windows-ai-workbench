package com.hexanima.npu;
import java.nio.FloatBuffer;
final class ChannelStats {
 final double mean,std; final float min,max; final int nonfinite;
 ChannelStats(FloatBuffer z,int offset,int count){
  if(offset<0||count<0||offset>z.limit()-count)throw new IllegalArgumentException("channel bounds");
  double m=0,m2=0;float lo=Float.POSITIVE_INFINITY,hi=Float.NEGATIVE_INFINITY;int n=0;
  for(int i=0;i<count;i++){float v=z.get(offset+i);if(!Float.isFinite(v))continue;n++;double delta=v-m;m+=delta/n;m2+=delta*(v-m);lo=Math.min(lo,v);hi=Math.max(hi,v);}
  mean=n==0?0:m;std=n==0?0:Math.sqrt(Math.max(0,m2/n));min=n==0?0:lo;max=n==0?0:hi;nonfinite=count-n;
 }
}
