// Point the big download button at the visitor's system, and highlight its install steps.
(function () {
  const p = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent).toLowerCase();
  const os = /mac|iphone|ipad/.test(p) ? 'mac' : /linux|x11|cros/.test(p) && !/android/.test(p) ? 'linux' : 'windows';
  const btn = document.getElementById('download');
  if (os !== 'windows') {
    const link = document.querySelector(`[data-os="${os}"]`);
    btn.href = link.href;
    btn.textContent = os === 'mac' ? 'Download for macOS' : 'Download for Linux';
    link.textContent = 'Windows';
    link.href = 'https://github.com/Karthus3560/crewroom/releases/latest/download/CrewroomSetup.exe';
  }
  const card = document.getElementById(os === 'mac' ? 'macos' : os);
  if (card) card.classList.add('here');
})();
