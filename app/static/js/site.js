document.addEventListener('DOMContentLoaded', () => {
  const themeToggle = document.querySelector('.theme-toggle');
  const root = document.documentElement;

  const applyThemeButton = () => {
    if (!themeToggle) return;
    const isDark = root.dataset.theme === 'dark';
    const icon = themeToggle.querySelector('i');
    const label = themeToggle.querySelector('span');
    themeToggle.setAttribute('aria-label', isDark ? 'Ativar tema claro' : 'Ativar tema escuro');
    themeToggle.setAttribute('title', isDark ? 'Ativar tema claro' : 'Ativar tema escuro');
    if (icon) icon.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
    if (label) label.textContent = isDark ? 'Tema claro' : 'Tema escuro';
  };

  applyThemeButton();
  themeToggle?.addEventListener('click', () => {
    const nextTheme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = nextTheme;
    try { localStorage.setItem('trivox-theme', nextTheme); } catch (error) {}
    applyThemeButton();
  });
  const menuButton = document.querySelector('.nav-toggle');
  const navLinks = document.querySelector('.nav-links');

  const setMenuState = (open) => {
    if (!menuButton || !navLinks) return;
    navLinks.classList.toggle('is-open', open);
    document.body.classList.toggle('menu-open', open);
    menuButton.setAttribute('aria-expanded', open ? 'true' : 'false');
    menuButton.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    const icon = menuButton.querySelector('i');
    if (icon) icon.className = open ? 'bi bi-x-lg' : 'bi bi-list';
  };

  if (menuButton && navLinks) {
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.addEventListener('click', () => {
      setMenuState(!navLinks.classList.contains('is-open'));
    });
    navLinks.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setMenuState(false)));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') setMenuState(false);
    });
    window.addEventListener('resize', () => {
      if (window.innerWidth > 620) setMenuState(false);
    });
  }

  const searchForm = document.querySelector('.nav-inner form');
  const searchInput = searchForm?.querySelector('input');
  const searchButton = searchForm?.querySelector('button');
  if (searchForm && searchInput && searchButton) {
    searchButton.addEventListener('click', (event) => {
      if (window.innerWidth <= 620 && !searchForm.classList.contains('is-open')) {
        event.preventDefault();
        searchForm.classList.add('is-open');
        searchInput.focus();
      }
    });
  }

  const updateAll = (selector, value) => {
    document.querySelectorAll(selector).forEach((element) => {
      element.textContent = value;
    });
  };

  fetch('https://economia.awesomeapi.com.br/json/last/USD-BRL')
    .then((response) => {
      if (!response.ok) throw new Error('Falha ao consultar cotação');
      return response.json();
    })
    .then((data) => {
      const rate = Number(data?.USDBRL?.bid);
      if (!Number.isFinite(rate)) throw new Error('Cotação inválida');
      updateAll('[data-dollar-value]', rate.toLocaleString('pt-BR', {
        style: 'currency',
        currency: 'BRL',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }));
      const pct = Number(data?.USDBRL?.pctChange);
      if (Number.isFinite(pct)) {
        const sign = pct > 0 ? '+' : '';
        updateAll('[data-dollar-change]', `${sign}${pct.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}%`);
      }
    })
    .catch(() => { updateAll('[data-dollar-value]', 'R$ --'); updateAll('[data-dollar-change]', '--%'); });

  const weatherUrl = 'https://api.open-meteo.com/v1/forecast?latitude=-25.5163&longitude=-54.5854&current=temperature_2m&temperature_unit=celsius&timezone=America%2FSao_Paulo';
  fetch(weatherUrl)
    .then((response) => {
      if (!response.ok) throw new Error('Falha ao consultar temperatura');
      return response.json();
    })
    .then((data) => {
      const temperature = Number(data?.current?.temperature_2m);
      if (!Number.isFinite(temperature)) throw new Error('Temperatura inválida');
      updateAll('[data-weather-value]', `${Math.round(temperature)}°C`);
    })
    .catch(() => updateAll('[data-weather-value]', '--°C'));
});

// Carrossel de categorias da home no mobile: setas + swipe/arraste nativo.
document.addEventListener('DOMContentLoaded', () => {
  const carousel = document.querySelector('[data-category-carousel]');
  const track = carousel?.querySelector('[data-category-track]');
  const prev = carousel?.querySelector('[data-category-prev]');
  const next = carousel?.querySelector('[data-category-next]');
  if (!carousel || !track || !prev || !next) return;

  const slides = () => Array.from(track.querySelectorAll('.popular-column'));
  const currentIndex = () => {
    const width = track.clientWidth || 1;
    return Math.max(0, Math.min(slides().length - 1, Math.round(track.scrollLeft / width)));
  };
  const goTo = (index) => {
    const items = slides();
    if (!items.length) return;
    const target = Math.max(0, Math.min(items.length - 1, index));
    items[target].scrollIntoView({behavior:'smooth', block:'nearest', inline:'start'});
  };

  prev.addEventListener('click', () => goTo(currentIndex() - 1));
  next.addEventListener('click', () => goTo(currentIndex() + 1));
});
