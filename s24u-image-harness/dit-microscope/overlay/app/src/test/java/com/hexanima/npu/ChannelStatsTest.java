package com.hexanima.npu;
import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.FloatBuffer;
public class ChannelStatsTest {
 @Test public void observesOnlySelectedChannel(){ChannelStats s=new ChannelStats(FloatBuffer.wrap(new float[]{999,-1,0,1,999}),1,3);assertEquals(0,s.mean,1e-12);assertEquals(Math.sqrt(2.0/3),s.std,1e-12);assertEquals(-1,s.min,0);assertEquals(1,s.max,0);assertEquals(0,s.nonfinite);}
 @Test public void reportsNonfiniteWithoutPoisoningStatistics(){ChannelStats s=new ChannelStats(FloatBuffer.wrap(new float[]{Float.NaN,2,Float.POSITIVE_INFINITY,4}),0,4);assertEquals(3,s.mean,0);assertEquals(1,s.std,0);assertEquals(2,s.nonfinite);}
 @Test public void emptyFiniteSetIsExplicit(){ChannelStats s=new ChannelStats(FloatBuffer.wrap(new float[]{Float.NaN}),0,1);assertEquals(1,s.nonfinite);assertEquals(0,s.mean,0);assertEquals(0,s.std,0);}
 @Test(expected=IllegalArgumentException.class) public void rejectsOutOfBoundsChannel(){new ChannelStats(FloatBuffer.wrap(new float[]{1}),1,1);}
}
