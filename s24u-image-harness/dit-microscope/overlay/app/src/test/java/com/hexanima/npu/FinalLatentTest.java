package com.hexanima.npu;
import org.junit.Test;import static org.junit.Assert.*;import java.nio.*;
public class FinalLatentTest {
 byte[] bytes(int... x){ByteBuffer b=ByteBuffer.allocate(x.length*4).order(ByteOrder.LITTLE_ENDIAN);for(int v:x)b.putInt(v);return b.array();}
 @Test public void chwPreserved(){assertArrayEquals(bytes(1,2,2,7,10,20,30,40),FinalLatent.wrap(bytes(10,20,30,40),1,2,2,7,false));}
 @Test public void tokensTransposed(){assertArrayEquals(bytes(1,2,2,15,10,30,20,40),FinalLatent.wrap(bytes(10,20,30,40),1,2,2,15,true));}
 @Test(expected=IllegalArgumentException.class) public void rejectsTruncated(){FinalLatent.wrap(bytes(1),1,2,2,3,false);}
 @Test(expected=IllegalArgumentException.class) public void rejectsInvalidShape(){FinalLatent.wrap(bytes(1),0,1,1,0,false);}
}
