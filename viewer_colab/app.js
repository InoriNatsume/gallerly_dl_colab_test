const grid = document.getElementById("grid");
const emptyState = document.getElementById("empty");
const emptyTitle = document.getElementById("emptyTitle");
const emptySub = document.getElementById("emptySub");
const stats = document.getElementById("stats");
const rootPath = document.getElementById("rootPath");
const searchInput = document.getElementById("searchInput");

const lightbox = document.getElementById("lightbox");
const lightboxImage = document.getElementById("lightboxImage");
const lightboxLoading = document.getElementById("lightboxLoading");
const metaTitle = document.getElementById("metaTitle");
const metaCaption = document.getElementById("metaCaption");
const metaTags = document.getElementById("metaTags");

let allItems = [];
let filteredItems = [];
let activeIndex = -1;
let observer = null;

function normalizeText(text) {
  return (text || "").toLowerCase();
}

function buildSearchIndex(item) {
  const tags = [
    ...(item.tags?.artist || []),
    ...(item.tags?.copyright || []),
    ...(item.tags?.character || []),
    ...(item.tags?.general || []),
  ];
  return normalizeText(
    [item.name, item.caption, tags.join(" ")].filter(Boolean).join(" ")
  );
}

function applyFilter(query) {
  const q = normalizeText(query);
  if (!q) {
    filteredItems = [...allItems];
  } else {
    filteredItems = allItems.filter((item) =>
      item._searchIndex.includes(q)
    );
  }
  renderGrid();
}

function createCard(item, index) {
  const card = document.createElement("button");
  card.className = "card";
  card.type = "button";
  card.dataset.index = index;
  card.innerHTML = `
    <div class="thumb">
      <div class="thumb-placeholder">▦</div>
      <img data-src="${item.thumb_url || item.image_url}" alt="${item.name}" />
    </div>
    <div class="card-label">${item.name}</div>
  `;
  card.addEventListener("click", () => openLightbox(index));
  return card;
}

function setupObserver() {
  if (observer) observer.disconnect();
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const img = entry.target.querySelector("img");
        if (img && !img.src) {
          img.src = img.dataset.src;
          img.addEventListener(
            "load",
            () => img.classList.add("loaded"),
            { once: true }
          );
        }
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: "300px" }
  );
}

function renderGrid() {
  grid.innerHTML = "";
  if (filteredItems.length === 0) {
    emptyState.style.display = "block";
  } else {
    emptyState.style.display = "none";
    setupObserver();
    filteredItems.forEach((item, index) => {
      const card = createCard(item, index);
      grid.appendChild(card);
      observer.observe(card);
    });
  }
  stats.textContent = `${filteredItems.length} items`;
}

function renderTags(tags) {
  const groups = [
    { key: "artist", label: "artist" },
    { key: "copyright", label: "copyright" },
    { key: "character", label: "character" },
    { key: "general", label: "general" },
  ];
  metaTags.innerHTML = "";
  groups.forEach((group) => {
    const values = tags?.[group.key] || [];
    if (!values.length) return;
    const wrapper = document.createElement("div");
    wrapper.className = "tag-group";
    const title = document.createElement("div");
    title.className = "tag-title";
    title.textContent = group.label;
    const list = document.createElement("div");
    list.className = "tag-list";
    values.forEach((value) => {
      const tag = document.createElement("span");
      tag.className = `tag ${group.key === "general" ? "highlight" : ""}`;
      tag.textContent = value;
      list.appendChild(tag);
    });
    wrapper.appendChild(title);
    wrapper.appendChild(list);
    metaTags.appendChild(wrapper);
  });
}

function openLightbox(index) {
  const item = filteredItems[index];
  if (!item) return;
  activeIndex = index;
  lightboxLoading.classList.add("show");
  const displayUrl = item.display_url || item.image_url;
  lightboxImage.src = displayUrl;
  lightboxImage.alt = item.name;
  metaTitle.textContent = item.name;
  metaCaption.textContent = item.caption || "-";
  renderTags(item.tags || {});
  lightbox.classList.add("show");
  lightbox.setAttribute("aria-hidden", "false");

  const fullUrl = item.image_url;
  if (fullUrl && displayUrl !== fullUrl) {
    const fullImage = new Image();
    fullImage.src = fullUrl;
    fullImage.onload = () => {
      if (activeIndex === index) {
        lightboxImage.src = fullUrl;
      }
    };
  }
}

lightboxImage.addEventListener("load", () => {
  lightboxLoading.classList.remove("show");
});

function closeLightbox() {
  lightbox.classList.remove("show");
  lightbox.setAttribute("aria-hidden", "true");
  lightboxImage.src = "";
  activeIndex = -1;
}

function moveLightbox(delta) {
  if (activeIndex < 0) return;
  const next = activeIndex + delta;
  if (next < 0 || next >= filteredItems.length) return;
  openLightbox(next);
}

async function fetchItems() {
  const response = await fetch("/api/items");
  const data = await response.json();
  rootPath.textContent = data.root || "Local dataset";
  if (!data.ready) {
    emptyTitle.textContent = "Indexing dataset...";
    emptySub.textContent = `Scanned ${data.scanned || 0} items`;
    emptyState.style.display = "block";
    stats.textContent = "Indexing...";
    setTimeout(fetchItems, 1500);
    return;
  }
  emptyTitle.textContent = "No items";
  emptySub.textContent = "Check your dataset path or filters.";
  allItems = (data.items || []).map((item) => ({
    ...item,
    _searchIndex: buildSearchIndex(item),
  }));
  filteredItems = [...allItems];
  renderGrid();
}

lightbox.addEventListener("click", (event) => {
  const action = event.target.dataset.action;
  if (action === "close") closeLightbox();
});

document.addEventListener("keydown", (event) => {
  if (!lightbox.classList.contains("show")) return;
  if (event.key === "Escape") closeLightbox();
  if (event.key === "ArrowRight") moveLightbox(1);
  if (event.key === "ArrowLeft") moveLightbox(-1);
});

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", (event) => {
    const action = event.target.dataset.action;
    if (action === "next") moveLightbox(1);
    if (action === "prev") moveLightbox(-1);
  });
});

searchInput.addEventListener("input", (event) => {
  applyFilter(event.target.value);
});

fetchItems().catch((err) => {
  rootPath.textContent = "Failed to load dataset";
  stats.textContent = "0 items";
  console.error(err);
});
