package com.hexanima.npu;
import java.nio.*;
/** Wraps the engine's final FP32 latent. Klein tokens are NC; Qwen/MOSS already CHW. */
final class FinalLatent {
 static byte[] wrap(byte[] data,int h,int w,int c,int step,boolean tokens) {
  if(h<=0||w<=0||c<=0||step<0||16L+4L*h*w*c>32L*1024*1024||data.length!=4L*h*w*c)throw new IllegalArgumentException("final latent size");
  ByteBuffer out=ByteBuffer.allocate(16+data.length).order(ByteOrder.LITTLE_ENDIAN);
  out.putInt(h).putInt(w).putInt(c).putInt(step);
  if(!tokens)out.put(data);
  else {ByteBuffer in=ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);int n=h*w;
   for(int ch=0;ch<c;ch++)for(int t=0;t<n;t++)out.putInt(in.getInt(4*(t*c+ch)));}
  return out.array();
 }
}
