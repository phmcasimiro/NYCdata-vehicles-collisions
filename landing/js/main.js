/* ==========================================================================
   NYC Collisions Analytics — Landing Page Interactivity
   Pure vanilla ES6+ — zero dependencies
   ========================================================================== */

(function () {
  'use strict';

  // ========================================================================
  // 1. NAVBAR — Sticky scroll shadow + active section highlighting
  // ========================================================================
  const navbar = document.getElementById('navbar');
  const navLinks = document.querySelectorAll('.navbar__link');
  const sections = document.querySelectorAll('section[id]');

  function handleNavbarScroll() {
    if (window.scrollY > 60) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  }

  function highlightActiveSection() {
    const scrollPos = window.scrollY + 120;

    sections.forEach(function (section) {
      const sectionTop = section.offsetTop;
      const sectionHeight = section.offsetHeight;
      const sectionId = section.getAttribute('id');

      if (scrollPos >= sectionTop && scrollPos < sectionTop + sectionHeight) {
        navLinks.forEach(function (link) {
          link.classList.remove('active');
          if (link.getAttribute('data-section') === sectionId) {
            link.classList.add('active');
          }
        });
      }
    });
  }

  window.addEventListener('scroll', function () {
    handleNavbarScroll();
    highlightActiveSection();
  }, { passive: true });

  // ========================================================================
  // 2. MOBILE MENU — Hamburger toggle
  // ========================================================================
  const hamburger = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobile-menu');

  if (hamburger && mobileMenu) {
    hamburger.addEventListener('click', function () {
      hamburger.classList.toggle('open');
      mobileMenu.classList.toggle('open');
    });

    // Close mobile menu when a link is clicked
    mobileMenu.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        hamburger.classList.remove('open');
        mobileMenu.classList.remove('open');
      });
    });
  }

  // ========================================================================
  // 3. SCROLL REVEAL — IntersectionObserver for fade-in-up animations
  // ========================================================================
  const revealElements = document.querySelectorAll('.reveal');

  if ('IntersectionObserver' in window) {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          revealObserver.unobserve(entry.target);
        }
      });
    }, {
      threshold: 0.1,
      rootMargin: '0px 0px -50px 0px'
    });

    revealElements.forEach(function (el) {
      revealObserver.observe(el);
    });
  } else {
    // Fallback for older browsers
    revealElements.forEach(function (el) {
      el.classList.add('visible');
    });
  }

  // ========================================================================
  // 4. ANIMATED COUNTERS — KPI values with counting animation
  // ========================================================================
  var countersAnimated = false;
  var kpiElements = document.querySelectorAll('.hero__kpi-value');

  function formatNumber(num) {
    return num.toLocaleString('en-US');
  }

  function animateCounter(element) {
    var target = parseInt(element.getAttribute('data-target'), 10);
    var suffix = element.getAttribute('data-suffix') || '';
    var duration = 2000;
    var startTime = null;

    function easeOutQuart(t) {
      return 1 - Math.pow(1 - t, 4);
    }

    function step(currentTime) {
      if (!startTime) startTime = currentTime;
      var elapsed = currentTime - startTime;
      var progress = Math.min(elapsed / duration, 1);
      var easedProgress = easeOutQuart(progress);
      var currentValue = Math.floor(easedProgress * target);

      element.textContent = formatNumber(currentValue) + suffix;

      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        element.textContent = formatNumber(target) + suffix;
      }
    }

    requestAnimationFrame(step);
  }

  function initCounters() {
    if (countersAnimated) return;

    var heroSection = document.getElementById('hero');
    if (!heroSection) return;

    var rect = heroSection.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) {
      countersAnimated = true;
      kpiElements.forEach(function (el) {
        animateCounter(el);
      });
    }
  }

  // Trigger counters on scroll or on load if already visible
  window.addEventListener('scroll', initCounters, { passive: true });
  window.addEventListener('load', function () {
    loadDynamicKPIs();
  });

  async function loadDynamicKPIs() {
    var API_STATUS_URL = 'http://localhost:8050/api/status';
    try {
      var response = await fetch(API_STATUS_URL);
      if (!response.ok) throw new Error('Falha na resposta da API');
      var data = await response.json();

      // Atualiza o target de Records Processed (Aprovados + Rejeitados)
      var totalProcessed = data.total_approved + data.total_rejected_dlq;
      var processedEl = document.querySelector('[data-kpi="records-processed"]');
      if (processedEl) {
        processedEl.setAttribute('data-target', totalProcessed);
      }

      // Quantidade da última carga incremental
      var lastQtyEl = document.querySelector('[data-kpi="last-ingest-qty"]');
      if (lastQtyEl) {
        lastQtyEl.setAttribute('data-target', data.last_ingest_qty);
      }

      // Registros aprovados/validados
      var approvedEl = document.querySelector('[data-kpi="records-approved"]');
      if (approvedEl) {
        approvedEl.setAttribute('data-target', data.total_approved);
      }

      // Registros rejeitados (DLQ)
      var rejectedEl = document.querySelector('[data-kpi="records-rejected"]');
      if (rejectedEl) {
        rejectedEl.setAttribute('data-target', data.total_rejected_dlq);
      }

      // Data da última coleta
      var lastDateEl = document.getElementById('last-ingest-date');
      if (lastDateEl && data.last_ingest_date !== 'N/A') {
        var dateObj = new Date(data.last_ingest_date);
        var formattedDate = dateObj.toLocaleDateString('pt-BR') + ' às ' + dateObj.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        lastDateEl.textContent = formattedDate;
      }

      // Data do acidente mais recente carregado (watermark)
      var lastAccidentEl = document.getElementById('last-accident-insert');
      if (lastAccidentEl && data.watermark_crash_date && data.watermark_crash_date !== 'N/A') {
        var accidentDate = new Date(data.watermark_crash_date);
        lastAccidentEl.textContent = accidentDate.toLocaleDateString('pt-BR');
      }

      // Reinicializa contadores para ler os novos targets dinâmicos
      kpiElements = document.querySelectorAll('.hero__kpi-value');
      countersAnimated = false;
      initCounters();
    } catch (e) {
      console.warn('Erro ao carregar telemetria em tempo real (fallback estático ativo):', e);
      // Dispara contadores estáticos de fallback
      initCounters();
    }
  }

  // ========================================================================
  // 5. ARCHITECTURE TABS — Switch content panels
  // ========================================================================
  var tabButtons = document.querySelectorAll('.architecture__tab');
  var tabContents = document.querySelectorAll('.architecture__content');

  tabButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var targetTab = btn.getAttribute('data-tab');

      // Update active button
      tabButtons.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');

      // Update active content
      tabContents.forEach(function (content) {
        content.classList.remove('active');
      });

      var targetContent = document.getElementById('tab-' + targetTab);
      if (targetContent) {
        targetContent.classList.add('active');
      }
    });
  });

  // ========================================================================
  // 6. DASHBOARD IFRAME — Loading state + fallback detection
  // ========================================================================
  var dashIframe = document.getElementById('dash-iframe');
  var dashLoading = document.getElementById('dash-loading');
  var dashFallback = document.getElementById('dash-fallback');

  // Determine the dashboard URL based on environment
  var DASH_LOCAL_URL = 'http://localhost:8050';

  // For deployed version, you would set this to your Render URL:
  // var DASH_DEPLOY_URL = 'https://your-dash-app.onrender.com';

  var isLocalhost = window.location.hostname === 'localhost' ||
                    window.location.hostname === '127.0.0.1' ||
                    window.location.protocol === 'file:';

  var dashUrl = DASH_LOCAL_URL;

  function showFallback() {
    if (dashLoading) dashLoading.classList.add('hidden');
    if (dashFallback) dashFallback.classList.add('visible');
    if (dashIframe) dashIframe.style.display = 'none';
  }

  function showDashboard() {
    if (dashLoading) dashLoading.classList.add('hidden');
    if (dashFallback) dashFallback.classList.remove('visible');
    if (dashIframe) dashIframe.style.display = 'block';
  }

  if (dashIframe) {
    // Try to load the dashboard
    dashIframe.src = dashUrl;

    dashIframe.addEventListener('load', function () {
      // iframe loaded something — could be the Dash app or an error page
      // The load event fires even for connection errors in some browsers,
      // so we add a small delay to check
      setTimeout(function () {
        showDashboard();
      }, 500);
    });

    dashIframe.addEventListener('error', function () {
      showFallback();
    });

    // Timeout fallback — if Dash doesn't load within 12 seconds
    setTimeout(function () {
      if (dashLoading && !dashLoading.classList.contains('hidden')) {
        showFallback();
      }
    }, 12000);
  }

  // ========================================================================
  // 7. SMOOTH SCROLL — Override default anchor behavior
  // ========================================================================
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      var targetId = anchor.getAttribute('href');
      if (targetId === '#') return;

      var targetElement = document.querySelector(targetId);
      if (targetElement) {
        e.preventDefault();
        targetElement.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });

  // ========================================================================
  // 8. NETWORK MESH — Plexus constellation canvas animation
  // ========================================================================
  (function initNetworkMesh() {
    var canvas = document.getElementById('hero-network');
    if (!canvas) return;

    var ctx = canvas.getContext('2d');
    var animationId = null;
    var isVisible = true;

    // Configuration
    var CONFIG = {
      nodeCount: 65,
      connectionDistance: 150,
      nodeSpeed: 0.3,
      nodeMinRadius: 1.5,
      nodeMaxRadius: 3,
      nodeColor: { r: 236, g: 179, b: 101 },   // --gold-accent
      lineColor: { r: 236, g: 179, b: 101 },
      nodeOpacity: 0.5,
      lineMaxOpacity: 0.15,
      mouseRadius: 180
    };

    var nodes = [];
    var mouse = { x: -1000, y: -1000 };

    // Resize canvas to fill hero section
    function resize() {
      var rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
    }

    // Initialize nodes
    function createNodes() {
      nodes = [];
      for (var i = 0; i < CONFIG.nodeCount; i++) {
        nodes.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          vx: (Math.random() - 0.5) * CONFIG.nodeSpeed * 2,
          vy: (Math.random() - 0.5) * CONFIG.nodeSpeed * 2,
          radius: CONFIG.nodeMinRadius + Math.random() * (CONFIG.nodeMaxRadius - CONFIG.nodeMinRadius),
          baseOpacity: 0.2 + Math.random() * 0.4
        });
      }
    }

    // Update node positions
    function updateNodes() {
      for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];

        node.x += node.vx;
        node.y += node.vy;

        // Bounce off edges with soft padding
        if (node.x < 0 || node.x > canvas.width) node.vx *= -1;
        if (node.y < 0 || node.y > canvas.height) node.vy *= -1;

        // Keep within bounds
        node.x = Math.max(0, Math.min(canvas.width, node.x));
        node.y = Math.max(0, Math.min(canvas.height, node.y));
      }
    }

    // Draw connections between nearby nodes
    function drawConnections() {
      for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
          var dx = nodes[i].x - nodes[j].x;
          var dy = nodes[i].y - nodes[j].y;
          var dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < CONFIG.connectionDistance) {
            var opacity = (1 - dist / CONFIG.connectionDistance) * CONFIG.lineMaxOpacity;

            // Brighten connections near mouse
            var midX = (nodes[i].x + nodes[j].x) / 2;
            var midY = (nodes[i].y + nodes[j].y) / 2;
            var mouseDist = Math.sqrt(
              Math.pow(midX - mouse.x, 2) + Math.pow(midY - mouse.y, 2)
            );
            if (mouseDist < CONFIG.mouseRadius) {
              opacity += (1 - mouseDist / CONFIG.mouseRadius) * 0.15;
            }

            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.strokeStyle = 'rgba(' + CONFIG.lineColor.r + ',' + CONFIG.lineColor.g + ',' + CONFIG.lineColor.b + ',' + opacity.toFixed(3) + ')';
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }
      }
    }

    // Draw nodes
    function drawNodes() {
      for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];
        var opacity = node.baseOpacity * CONFIG.nodeOpacity;

        // Brighten nodes near mouse
        var mouseDist = Math.sqrt(
          Math.pow(node.x - mouse.x, 2) + Math.pow(node.y - mouse.y, 2)
        );
        if (mouseDist < CONFIG.mouseRadius) {
          opacity += (1 - mouseDist / CONFIG.mouseRadius) * 0.4;
        }

        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(' + CONFIG.nodeColor.r + ',' + CONFIG.nodeColor.g + ',' + CONFIG.nodeColor.b + ',' + opacity.toFixed(3) + ')';
        ctx.fill();
      }
    }

    // Animation loop
    function animate() {
      if (!isVisible) {
        animationId = requestAnimationFrame(animate);
        return;
      }

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      updateNodes();
      drawConnections();
      drawNodes();
      animationId = requestAnimationFrame(animate);
    }

    // Mouse tracking (relative to hero section)
    var heroSection = document.getElementById('hero');
    if (heroSection) {
      heroSection.addEventListener('mousemove', function (e) {
        var rect = canvas.getBoundingClientRect();
        mouse.x = e.clientX - rect.left;
        mouse.y = e.clientY - rect.top;
      });

      heroSection.addEventListener('mouseleave', function () {
        mouse.x = -1000;
        mouse.y = -1000;
      });
    }

    // Pause animation when hero is not visible (performance)
    if ('IntersectionObserver' in window) {
      var heroObserver = new IntersectionObserver(function (entries) {
        isVisible = entries[0].isIntersecting;
      }, { threshold: 0 });
      heroObserver.observe(canvas.parentElement);
    }

    // Handle window resize
    var resizeTimeout;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(function () {
        resize();
        createNodes();
      }, 200);
    });

    // Initialize
    resize();
    createNodes();
    animate();
  })();

})();
