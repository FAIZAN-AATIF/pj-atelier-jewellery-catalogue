
const $ = s => document.querySelector(s);

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
}[c]));

let token = sessionStorage.getItem('pj_admin_token') || '';
let categories = [];
let products = [];
let uploadedImage = null;

async function api(url, opts = {}) {
    opts.headers = {
        ...(opts.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
    };

    if (
        opts.body &&
        typeof opts.body === 'object' &&
        !(opts.body instanceof FormData)
    ) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(opts.body);
    }

    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({
        detail: 'Unexpected server response'
    }));

    if (!r.ok) {
        throw new Error(data.detail || 'Request failed');
    }

    return data;
}

function message(el, text, error = false) {
    $(el).textContent = text;
    $(el).style.color = error ? '#a13c32' : '';
}

function loginView() {
    $('#login-panel').classList.remove('hidden');
    $('#dashboard').classList.add('hidden');
}

function dashboardView() {
    $('#login-panel').classList.add('hidden');
    $('#dashboard').classList.remove('hidden');
    loadDashboard();
}

// ADMIN LOGIN

$('#login-form').addEventListener('submit', async e => {
    e.preventDefault();
    message('#login-error', '');

    const data = Object.fromEntries(new FormData(e.target));

    try {
        const result = await api('/api/auth/login', {
            method: 'POST',
            body: data
        });

        token = result.access_token;
        sessionStorage.setItem('pj_admin_token', token);
        dashboardView();

    } catch (err) {
        message('#login-error', err.message, true);
    }
});

// ADMIN LOGOUT

$('#logout').onclick = () => {
    token = '';
    sessionStorage.removeItem('pj_admin_token');
    loginView();
};

// DASHBOARD

async function loadDashboard() {
    try {
        [categories, products] = await Promise.all([
            api('/api/categories'),
            api('/api/admin/products')
        ]);

        const stats = await api('/api/admin/stats');

        $('#stats').innerHTML = [
            ['Total products', stats.total_products],
            ['Published', stats.published],
            ['Drafts', stats.drafts],
            ['Categories', stats.categories]
        ].map(([label, value]) => `
            <div class="stat-card">
                <span>${label}</span>
                <strong>${value}</strong>
            </div>
        `).join('');

        $('#admin-category').innerHTML =
            '<option value="">Uncategorised</option>' +
            categories.map(c =>
                `<option value="${c.id}">${esc(c.name)}</option>`
            ).join('');

        renderAdminProducts();

    } catch (e) {
        if (/token|sign-in|session/i.test(e.message)) {
            token = '';
            sessionStorage.removeItem('pj_admin_token');
            loginView();
        } else {
            alert(e.message);
        }
    }
}

// PRODUCT LIST

function renderAdminProducts() {
    const host = $('#admin-products');

    if (!products.length) {
        host.innerHTML =
            '<div class="empty-state">No designs yet. Add your first product.</div>';
        return;
    }

    host.innerHTML = products.map(p => `
        <article class="admin-product">
            <div>
                ${p.image_url
                    ? `<img src="${esc(p.image_url)}" alt="${esc(p.title)}">`
                    : '<div class="mini-placeholder">PJ</div>'
                }
            </div>

            <div>
                <h3>${esc(p.title)}</h3>
                <p>${esc(p.sku)} · ${esc(p.category)}</p>
                <span class="pill ${p.status === 'published' && !p.archived ? 'live' : ''}">
                    ${p.archived ? 'Archived' : esc(p.status)}
                </span>
            </div>

            <div class="product-actions">
                <button data-edit="${p.id}">Edit</button>
                ${p.archived ? '' : `<button data-archive="${p.id}">Archive</button>`}
            </div>
        </article>
    `).join('');

    host.querySelectorAll('[data-edit]').forEach(b => {
        b.onclick = () => editProduct(+b.dataset.edit);
    });

    host.querySelectorAll('[data-archive]').forEach(b => {
        b.onclick = () => archiveProduct(+b.dataset.archive);
    });
}

// IMAGE PATH HELPER

function getStoredImagePath(imageUrl) {
    if (!imageUrl) return null;

    const prefix = '/uploads/';

    if (!imageUrl.startsWith(prefix)) {
        return null;
    }

    return imageUrl.slice(prefix.length);
}

// EDIT PRODUCT

function editProduct(id) {
    const p = products.find(x => x.id === id);
    if (!p) return;

    const f = $('#product-form');
    const storedPath = getStoredImagePath(p.image_url);

    f.elements.id.value = p.id;
    f.elements.image_path.value = storedPath || '';
    f.elements.title.value = p.title;
    f.elements.sku.value = p.sku;
    f.elements.category_id.value = p.category_id || '';
    f.elements.status.value = p.status;
    f.elements.description.value = p.description;
    f.elements.tags.value = p.tags.join(', ');

    uploadedImage = storedPath;

    $('#editor-title').textContent = 'Edit design';
    $('#ai-button').disabled = !uploadedImage;

    $('#image-preview').innerHTML = p.image_url
        ? `<img src="${esc(p.image_url)}" alt="Current product image">
           <small>Current product image · choose another to replace</small>`
        : `<span class="upload-icon">＋</span>
           <b>Upload a jewellery image</b>`;

    $('#save-message').textContent = '';

    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

// CLEAR FORM

function clearForm() {
    const f = $('#product-form');

    f.reset();
    f.elements.id.value = '';
    f.elements.image_path.value = '';

    uploadedImage = null;

    $('#editor-title').textContent = 'Add a design';
    $('#ai-button').disabled = true;

    $('#image-preview').innerHTML = `
        <span class="upload-icon">＋</span>
        <b>Drop a jewellery image here</b>
        <small>or click to browse · JPG, PNG, WEBP · up to 8 MB</small>
    `;

    message('#ai-message', '');
    message('#save-message', '');
}

$('#reset-form').onclick = clearForm;
$('#refresh').onclick = loadDashboard;

// GET SELECTED CATEGORY

function getSelectedCategory() {
    const f = $('#product-form');
    const categoryId = f.elements.category_id.value;

    if (!categoryId) {
        return 'uncategorised';
    }

    const selected = categories.find(
        c => String(c.id) === String(categoryId)
    );

    if (!selected) {
        throw new Error('Please select a valid product category.');
    }

    return selected.name.toLowerCase().trim();
}

// IMAGE UPLOAD

$('#upload-zone').addEventListener('click', e => {
    if (!e.target.closest('#ai-button')) {
        $('#image-file').click();
    }
});

$('#image-file').addEventListener('change', async e => {
    const file = e.target.files[0];

    if (!file) return;

    if (file.size > 8 * 1024 * 1024) {
        message(
            '#ai-message',
            'Image exceeds 8 MB. Choose a smaller image.',
            true
        );
        e.target.value = '';
        return;
    }

    if (![
        'image/jpeg',
        'image/png',
        'image/webp',
        'image/gif'
    ].includes(file.type)) {
        message(
            '#ai-message',
            'Use JPG, PNG, WEBP or GIF.',
            true
        );
        e.target.value = '';
        return;
    }

    let category;

    try {
        category = getSelectedCategory();
    } catch (err) {
        message('#ai-message', err.message, true);
        e.target.value = '';
        return;
    }

    const previewUrl = URL.createObjectURL(file);

    $('#image-preview').innerHTML = `
        <img src="${previewUrl}" alt="Image preview">
        <small>${esc(file.name)}</small>
    `;

    message('#ai-message', 'Uploading image...');

    try {
        const fd = new FormData();

        fd.append('file', file);
        fd.append('category', category);

        const result = await api('/api/uploads', {
            method: 'POST',
            body: fd
        });

        uploadedImage = result.image_path;

        $('#product-form').elements.image_path.value = uploadedImage;

        $('#image-preview').innerHTML = `
            <img src="${esc(result.image_url)}" alt="Uploaded product image">
            <small>${esc(uploadedImage)}</small>
        `;

        $('#ai-button').disabled = false;

        message(
            '#ai-message',
            `Image uploaded successfully to ${category}.`
        );

    } catch (err) {
        uploadedImage = null;
        $('#ai-button').disabled = true;
        message('#ai-message', err.message, true);

    } finally {
        URL.revokeObjectURL(previewUrl);
    }
});

// AI PRODUCT SUGGESTIONS

$('#ai-button').onclick = async () => {
    if (!uploadedImage) return;

    const b = $('#ai-button');

    b.disabled = true;
    b.textContent = '✳ Analysing image...';

    message(
        '#ai-message',
        'AI is analysing visible design details. Please wait.'
    );

    try {
        const s = await api('/api/ai/suggest', {
            method: 'POST',
            body: {
                image_path: uploadedImage
            }
        });

        const f = $('#product-form');

        if (!f.elements.title.value) {
            f.elements.title.value = s.title;
        }

        if (!f.elements.description.value) {
            f.elements.description.value = s.description;
        }

        if (!f.elements.tags.value) {
            f.elements.tags.value = s.tags.join(', ');
        }

        const c = categories.find(
            x => x.name.toLowerCase() === s.category.toLowerCase()
        );

        if (c) {
            f.elements.category_id.value = c.id;
        }

        message(
            '#ai-message',
            `Suggestions generated with ${s.provider} (${s.model}). Review and edit all fields before saving.`
        );

    } catch (err) {
        message(
            '#ai-message',
            `${err.message} You can still enter product information manually and retry AI later.`,
            true
        );

    } finally {
        b.disabled = !uploadedImage;
        b.textContent = '✳ Generate with AI';
    }
};

// SAVE PRODUCT

$('#product-form').addEventListener('submit', async e => {
    e.preventDefault();

    const f = e.target;
    const id = f.elements.id.value;

    const payload = {
        sku: f.elements.sku.value.trim(),
        title: f.elements.title.value.trim(),
        description: f.elements.description.value.trim(),
        category_id: f.elements.category_id.value
            ? Number(f.elements.category_id.value)
            : null,
        tags: f.elements.tags.value
            .split(',')
            .map(t => t.trim())
            .filter(Boolean),
        status: f.elements.status.value,
        image_path: uploadedImage
    };

    try {
        const result = await api(
            id
                ? `/api/admin/products/${id}`
                : '/api/admin/products',
            {
                method: id ? 'PATCH' : 'POST',
                body: payload
            }
        );

        message(
            '#save-message',
            `Saved "${result.title}" as ${result.status}.`
        );

        clearForm();
        await loadDashboard();

    } catch (err) {
        message('#save-message', err.message, true);
    }
});

// ARCHIVE PRODUCT

async function archiveProduct(id) {
    if (!confirm(
        'Archive this product? It will no longer appear in the public catalogue.'
    )) return;

    try {
        await api(`/api/admin/products/${id}`, {
            method: 'DELETE'
        });

        await loadDashboard();

    } catch (e) {
        alert(e.message);
    }
}

// CATEGORY CREATION

$('#category-form').addEventListener('submit', async e => {
    e.preventDefault();

    const d = Object.fromEntries(new FormData(e.target));

    try {
        await api('/api/categories', {
            method: 'POST',
            body: d
        });

        e.target.reset();

        message('#category-message', 'Category added.');

        await loadDashboard();

    } catch (err) {
        message('#category-message', err.message, true);
    }
});

// INITIALIZE ADMIN

if (token) {
    dashboardView();
} else {
    loginView();
}
