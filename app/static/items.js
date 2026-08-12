async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  const isJson = response.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await response.json() : null;

  if (!response.ok) {
    const message = payload?.detail || `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  return payload;
}

function feedbackNode(button) {
  return button.closest('[data-item-id]')?.querySelector('[data-feedback]');
}

function setFeedback(button, message, isError = false) {
  const node = feedbackNode(button);
  if (!node) {
    return;
  }
  node.textContent = message;
  node.style.color = isError ? '#9f2d20' : '#1f4f45';
}

function getDraftPayload(root) {
  const title = root.querySelector('[data-field="title"]')?.value?.trim() || '';
  const description = root.querySelector('[data-field="description"]')?.value?.trim() || '';
  const keywordsRaw = root.querySelector('[data-field="keywords"]')?.value || '';
  const keywords = keywordsRaw
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

  return { title, description, keywords };
}

function splitList(value) {
  return (value || '')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function getMarketingStrategyPayload(root) {
  return {
    target_customer: root.querySelector('[data-strategy-field="target_customer"]')?.value?.trim() || null,
    buyer_intent: splitList(root.querySelector('[data-strategy-field="buyer_intent"]')?.value),
    positioning_angle: root.querySelector('[data-strategy-field="positioning_angle"]')?.value?.trim() || null,
    primary_value_proposition: root.querySelector('[data-strategy-field="primary_value_proposition"]')?.value?.trim() || null,
    selling_points: splitList(root.querySelector('[data-strategy-field="selling_points"]')?.value),
    search_keywords: splitList(root.querySelector('[data-strategy-field="search_keywords"]')?.value),
    long_tail_keywords: splitList(root.querySelector('[data-strategy-field="long_tail_keywords"]')?.value),
    style_keywords: splitList(root.querySelector('[data-strategy-field="style_keywords"]')?.value),
    merchandising_notes: splitList(root.querySelector('[data-strategy-field="merchandising_notes"]')?.value),
    recommended_primary_image_type: root.querySelector('[data-strategy-field="recommended_primary_image_type"]')?.value?.trim() || null,
    social_media_angles: splitList(root.querySelector('[data-strategy-field="social_media_angles"]')?.value),
    marketplace_notes: splitList(root.querySelector('[data-strategy-field="marketplace_notes"]')?.value),
    warnings: splitList(root.querySelector('[data-strategy-field="warnings"]')?.value),
  };
}

async function handleAction(button) {
  const root = button.closest('[data-item-id]');
  if (!root) {
    return;
  }

  const itemId = root.getAttribute('data-item-id');
  const action = button.getAttribute('data-action');
  const imageId = button.getAttribute('data-image-id');
  button.disabled = true;
  setFeedback(button, 'Working...');

  try {
    if (action === 'cache-images') {
      const result = await requestJson(`/items/${itemId}/images/cache`, { method: 'POST' });
      setFeedback(button, `Cached ${result.downloaded} image(s); ${result.failed} failed.`);
      window.location.reload();
      return;
    }

    if (action === 'analyze-images') {
      const result = await requestJson(`/items/${itemId}/images/analyze`, { method: 'POST' });
      setFeedback(button, `Analyzed ${result.analyzed} image(s); ${result.failed} failed.`);
      window.location.reload();
      return;
    }

    if (action === 'enhance') {
      const result = await requestJson(`/items/${itemId}/enhance`, {
        method: 'POST',
        body: JSON.stringify({ max_images: 4, force_regenerate: false }),
      });
      setFeedback(button, `Enhancement finished with status ${result.status}.`);
      window.location.reload();
      return;
    }

    if (action === 'regenerate-strategy') {
      await requestJson(`/items/${itemId}/marketing-strategy/regenerate`, {
        method: 'POST',
      });
      setFeedback(button, 'Marketing strategy regenerated.');
      window.location.reload();
      return;
    }

    if (action === 'regenerate-listing') {
      await requestJson(`/items/${itemId}/listing/regenerate`, {
        method: 'POST',
      });
      setFeedback(button, 'Listing draft regenerated.');
      window.location.reload();
      return;
    }

    if (action === 'save-strategy') {
      const payload = getMarketingStrategyPayload(root);
      await requestJson(`/items/${itemId}/marketing-strategy`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setFeedback(button, 'Marketing strategy saved.');
      window.location.reload();
      return;
    }

    if (action === 'save-draft') {
      const payload = getDraftPayload(root);
      await requestJson(`/items/${itemId}/draft`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setFeedback(button, 'Draft saved.');
      window.location.reload();
      return;
    }

    if (action === 'approve') {
      await requestJson(`/items/${itemId}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approved_by: 'local-user' }),
      });
      setFeedback(button, 'Item approved.');
      window.location.reload();
      return;
    }

    if (action === 'select-primary') {
      await requestJson(`/items/${itemId}/images/${imageId}/select-primary`, { method: 'POST' });
      setFeedback(button, 'Primary image updated.');
      window.location.reload();
      return;
    }

    if (action === 'use-original') {
      await requestJson(`/items/${itemId}/images/${imageId}/use-original`, { method: 'POST' });
      setFeedback(button, 'Original image selected for review.');
      window.location.reload();
      return;
    }

    if (action === 'use-enhanced') {
      await requestJson(`/items/${itemId}/images/${imageId}/use-enhanced`, { method: 'POST' });
      setFeedback(button, 'Enhanced image selected for review.');
      window.location.reload();
      return;
    }

    if (action === 'enhance-image') {
      const result = await requestJson(`/items/${itemId}/images/${imageId}/enhance`, {
        method: 'POST',
        body: JSON.stringify({ force_provider: 'auto', output_width: 1024, output_height: 1024 }),
      });
      setFeedback(button, `Image enhancement finished via ${result.processing_path}.`);
      window.location.reload();
      return;
    }

    if (action === 'validate-image') {
      await requestJson(`/items/${itemId}/images/${imageId}/validate`, { method: 'POST' });
      setFeedback(button, 'Image validation updated.');
      window.location.reload();
      return;
    }

    if (action === 'approve-image') {
      await requestJson(`/items/${itemId}/images/${imageId}/approve`, { method: 'POST' });
      setFeedback(button, 'Image approved for publishing.');
      window.location.reload();
      return;
    }

    if (action === 'reject-image') {
      await requestJson(`/items/${itemId}/images/${imageId}/reject`, { method: 'POST' });
      setFeedback(button, 'Image rejected.');
      window.location.reload();
      return;
    }
  } catch (error) {
    setFeedback(button, error.message || 'Request failed.', true);
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll('[data-action]').forEach((button) => {
  button.addEventListener('click', () => {
    handleAction(button);
  });
});
