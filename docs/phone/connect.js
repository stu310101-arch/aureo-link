(() => {
  const form = document.getElementById('connectForm');
  const address = document.getElementById('address');
  const error = document.getElementById('error');
  form.addEventListener('submit', event => {
    event.preventDefault();
    error.textContent = '';
    try {
      const url = new URL(address.value.trim());
      if (url.protocol !== 'https:' || url.username || url.password) throw new Error('invalid');
      if (url.hostname === 'stu310101-arch.github.io') throw new Error('入口本身不是電腦連線網址。請貼上 Windows 程式顯示的網址。');
      location.assign(url.href);
    } catch (problem) {
      error.textContent = problem.message === 'invalid' || problem instanceof TypeError
        ? '請貼上電腦程式提供的完整 https:// 連線網址。' : problem.message;
    }
  });
})();
