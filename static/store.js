
const $ = selector => document.querySelector(selector);

const esc = value =>
  String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[character]));

const tagsOf = product =>
  Array.isArray(product.tags) ? product.tags : [];

let products = [];
let categories = [];

async function api(url, options = {}) {
  const response = await fetch(url, options);

  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: 'Request failed'
    }));

    throw new Error(error.detail || 'Request failed');
  }

  return response.json();
}

function placeholder(name = 'PJ') {
  return `
    <div class="product-placeholder">
      ${esc(String(name).slice(0, 2).toUpperCase())}
      <span>ATELIER PJ</span>
    </div>
  `;
}

/* DISPLAY PRODUCTS */

function renderProducts() {
  const searchInput = $('#search');
  const categorySelect = $('#category');

  const query = searchInput.value.trim().toLowerCase();
  const selectedCategory = categorySelect.value;

  const filteredProducts = products.filter(product => {
    const searchableText = [
      product.title,
      product.description,
      product.sku,
      product.category,
      ...tagsOf(product)
    ].join(' ').toLowerCase();

    const matchesSearch =
      !query || searchableText.includes(query);

    const matchesCategory =
      !selectedCategory ||
      String(product.category_id) === selectedCategory;

    return matchesSearch && matchesCategory;
  });

  $('#product-grid').innerHTML = filteredProducts.length
    ? filteredProducts.map(product => `
        <article
          class="product-card"
          data-id="${Number(product.id)}"
          tabindex="0"
          role="button"
          aria-label="View ${esc(product.title)}"
        >
          <div class="product-image">
            ${
              product.image_url
                ? `
                  <img
                    loading="lazy"
                    src="${esc(product.image_url)}"
                    alt="${esc(product.title)}"
                  >
                `
                : placeholder(product.title)
            }

            <span class="product-badge">
              ${esc(product.category)}
            </span>
          </div>

          <div class="product-meta">
            <div>
              <h3>${esc(product.title)}</h3>
              <p>
                ${esc(
                  tagsOf(product).slice(0, 3).join(' · ') ||
                  product.sku
                )}
              </p>
            </div>

            <span class="product-arrow">↗</span>
          </div>
        </article>
      `).join('')
    : `
      <div class="empty-state">
        ${
          products.length
            ? 'No designs match your search. Try another term.'
            : 'The collection is being curated. Please check back soon.'
        }
      </div>
    `;

  $('#catalogue-message').textContent = filteredProducts.length
    ? `${filteredProducts.length} ${
        filteredProducts.length === 1 ? 'design' : 'designs'
      } in the collection`
    : '';

  document.querySelectorAll('.product-card').forEach(card => {
    const openProduct = () => {
      showProduct(Number(card.dataset.id));
    };

    card.addEventListener('click', openProduct);

    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openProduct();
      }
    });
  });
}

/* PRODUCT DETAILS */

function showProduct(id) {
  const product = products.find(item => item.id === id);

  if (!product) return;

  const productTags = tagsOf(product);

  $('#modal-content').innerHTML = `
    <div class="modal-image">
      ${
        product.image_url
          ? `
            <img
              src="${esc(product.image_url)}"
              alt="${esc(product.title)}"
            >
          `
          : placeholder(product.title)
      }
    </div>

    <div class="modal-details">
      <p class="eyebrow">
        ${esc(product.category)} / ${esc(product.sku)}
      </p>

      <h2>${esc(product.title)}</h2>

      <p>
        ${esc(
          product.description ||
          'A considered design, made to become part of your story.'
        )}
      </p>

      <p>
        ${
          productTags.map(tag =>
            `<span>${esc(tag)} · </span>`
          ).join('')
        }
      </p>

      <button class="button button-dark" id="detail-close">
        Back to collection <span>↗</span>
      </button>
    </div>
  `;

  $('#product-modal').classList.remove('hidden');

  $('#detail-close').onclick = closeProductModal;
}

function closeProductModal() {
  $('#product-modal').classList.add('hidden');
}

/* LOAD CATEGORIES AND PRODUCTS */

async function init() {
  $('#year').textContent = new Date().getFullYear();

  try {
    const [productData, categoryData] = await Promise.all([
      api('/api/products'),
      api('/api/categories')
    ]);

    products = Array.isArray(productData) ? productData : [];
    categories = Array.isArray(categoryData) ? categoryData : [];

    $('#category').innerHTML =
      '<option value="">All categories</option>' +
      categories.map(category => `
        <option value="${esc(category.id)}">
          ${esc(category.name)}
        </option>
      `).join('');

    renderProducts();

  } catch (error) {
    console.error('Catalogue loading error:', error);

    $('#product-grid').innerHTML = `
      <div class="empty-state">
        Unable to load the catalogue. Please refresh the page.
      </div>
    `;

    $('#catalogue-message').textContent = error.message;
  }
}

/* SEARCH AND FILTER EVENTS */

$('#search').addEventListener('input', renderProducts);

$('#category').addEventListener('change', renderProducts);

/* MODAL EVENTS */

$('#modal-close').addEventListener('click', closeProductModal);

$('#product-modal').addEventListener('click', event => {
  if (event.target.id === 'product-modal') {
    closeProductModal();
  }
});

document.addEventListener('keydown', event => {
  if (
    event.key === 'Escape' &&
    !$('#product-modal').classList.contains('hidden')
  ) {
    closeProductModal();
  }
});

/* START APPLICATION */

init();
