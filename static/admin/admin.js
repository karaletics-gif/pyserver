document.addEventListener("click", function (event) {
  var add = event.target.closest("[data-add-row]");
  if (add) {
    var list = document.getElementById(add.dataset.addRow);
    var template = document.getElementById(add.dataset.addRow + "-template");
    var next = list.querySelectorAll("[data-row]").length;
    var holder = document.createElement("div");
    holder.innerHTML = template.innerHTML.split("__i__").join(String(next)).trim();
    list.appendChild(holder.firstElementChild);
  }
  var remove = event.target.closest("[data-remove-row]");
  if (remove) {
    var row = remove.closest("[data-row]");
    row.querySelectorAll("input, textarea, select").forEach(function (el) { el.value = ""; });
    row.style.display = "none";
  }
});
