package com.hexanima.npu;
import android.os.Bundle;
import android.webkit.*;
import android.widget.*;
public class MicroscopeActivity extends Base {
 @Override protected void onCreate(Bundle b){super.onCreate(b);LinearLayout root=screen("DiT NPU · 显微镜",null);WebView web=new WebView(this);web.getSettings().setJavaScriptEnabled(true);web.getSettings().setAllowFileAccess(false);web.getSettings().setAllowContentAccess(false);web.setWebViewClient(new WebViewClient(){@Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return true;}});web.addJavascriptInterface(new Object(){@JavascriptInterface public String snapshot(){return Trace.snapshot(MicroscopeActivity.this,getIntent().getStringExtra("model"),getIntent().getStringExtra("modelName"));}@JavascriptInterface public String frame(String run,int i,int c){return Trace.frame(MicroscopeActivity.this,getIntent().getStringExtra("model"),run,i,c);}},"DitTrace");root.addView(web,new LinearLayout.LayoutParams(-1,dp(900)));web.loadUrl("file:///android_asset/dit_microscope.html");}
}
