// Pose la classe « dark » sur <html> avant le premier affichage, d'après le thème gardé dans le
// navigateur (src/hooks/useTheme.ts), sinon d'après celui du système : pas d'éclair clair.
;(function () {
  var choice = null
  try {
    choice = localStorage.getItem('forceupdate-theme')
  } catch {
    // stockage refusé : le thème du système
  }
  var dark =
    choice === 'dark' ||
    (choice !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
})()
