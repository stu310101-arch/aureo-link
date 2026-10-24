/* Camera stays inside the installed PWA; decoding works without BarcodeDetector. */
(() => {
  'use strict';
  let stream = null, frame = 0, callback = null, scanning = false, generation=0;
  const $ = id => document.getElementById(id);
  function stop() {
    generation++;
    scanning = false;
    cancelAnimationFrame(frame);
    for (const track of stream?.getTracks() || []) track.stop();
    stream = null;
    $('scanVideo').srcObject = null;
    $('scanner').hidden = true;
  }
  async function start(onCode) {
    stop(); callback = onCode;
    const current=generation;
    $('scanner').hidden = false;
    $('scanError').textContent = '請允許相機，對準電腦上的 QR Code。';
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('此瀏覽器無法開啟相機，請使用下方 8 位數連線碼。');
      const camera = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280}},audio:false});
      if(current!==generation){for(const track of camera.getTracks())track.stop();return;}
      stream=camera;
      const video = $('scanVideo'); video.srcObject = stream;
      await video.play();
      if(current!==generation)return;
      $('scanError').textContent = '將電腦的 QR Code 放入畫面中央';
      scanning = true;
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d', {willReadFrequently:true});
      let last = 0;
      function scan(now) {
        if (!scanning) return;
        if (now-last > 180 && video.readyState >= 2 && video.videoWidth) {
          last = now;
          canvas.width = Math.min(960, video.videoWidth);
          canvas.height = Math.round(video.videoHeight*canvas.width/video.videoWidth);
          context.drawImage(video,0,0,canvas.width,canvas.height);
          const pixels = context.getImageData(0,0,canvas.width,canvas.height);
          const code = window.jsQR(pixels.data,pixels.width,pixels.height,{inversionAttempts:'dontInvert'});
          if (code?.data) { const done=callback; stop(); done(code.data); return; }
        }
        frame=requestAnimationFrame(scan);
      }
      frame=requestAnimationFrame(scan);
    } catch (error) {
      for (const track of stream?.getTracks() || []) track.stop();
      stream = null;
      $('scanError').textContent = error.name === 'NotAllowedError'
        ? '相機權限未開啟。可在瀏覽器設定允許相機，或直接輸入下方 8 位數連線碼。'
        : error.message || '相機無法啟動，請使用 8 位數連線碼。';
    }
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  window.AmosScanner={start,stop};
})();
