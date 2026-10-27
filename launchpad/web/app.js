document.addEventListener("DOMContentLoaded", function () {
  var button = document.getElementById("copy");
  var field = document.getElementById("link");
  if (!button || !field) {
    return;
  }
  button.addEventListener("click", function () {
    field.select();
    var original = button.textContent;
    var done = function () {
      button.textContent = button.getAttribute("data-copied");
      setTimeout(function () {
        button.textContent = original;
      }, 2000);
    };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(field.value).then(done);
    } else {
      document.execCommand("copy");
      done();
    }
  });
});
