/**
 * Bloomberg digest trigger (Google Apps Script).
 *
 * GitHub's built-in cron scheduler is unreliable (since Aug 2026 scheduled runs are often
 * hours late or never start). This script runs in your Google account every 5 minutes,
 * checks Gmail for Bloomberg emails the digest hasn't processed yet, and only then
 * starts the GitHub workflow through the API.
 *
 * Setup: see README.md -> "Trigger (Google Apps Script)".
 * Needs Script Property GITHUB_TOKEN = fine-grained token with "Actions: Read and write"
 * on the bloomberg-news-digest repo only.
 */

const CONFIG = {
  repo: 'ZhiyangZhou98/bloomberg-news-digest',
  workflow: 'digest.yml',
  branch: 'master',
  query: 'from:noreply@news.bloomberg.com -label:BBG-Digest-Processed newer_than:1d',
  checkEveryMinutes: 5,
  retryAfterMinutes: 45,  // still unprocessed this long after a dispatch -> run again
  maxAttempts: 3,         // per email; stops retrying emails the digest deliberately skips
};

/** Main job, run by the time trigger. */
function checkAndDispatch() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return;
  try {
    const props = PropertiesService.getScriptProperties();
    const state = JSON.parse(props.getProperty('STATE') || '{}');  // threadKey -> {t, n}
    const now = Date.now();

    const threads = GmailApp.search(CONFIG.query, 0, 50);
    const keys = threads.map(t => t.getId() + ':' + t.getLastMessageDate().getTime());

    // Forget emails that are no longer pending (processed, or older than 1 day).
    const next = {};
    keys.forEach(k => { if (state[k]) next[k] = state[k]; });

    const due = keys.filter(k => {
      const s = next[k];
      if (!s) return true;                                   // new email
      return s.n < CONFIG.maxAttempts &&
             now - s.t > CONFIG.retryAfterMinutes * 60000;   // earlier run didn't process it
    });

    if (due.length) {
      dispatch_({ dry_run: 'false', lookback_days: '1' }, CONFIG.branch);
      due.forEach(k => { next[k] = { t: now, n: ((next[k] && next[k].n) || 0) + 1 }; });
      console.log('Dispatched digest for ' + due.length + ' email thread(s)');
    }
    props.setProperty('STATE', JSON.stringify(next));
  } catch (e) {
    notifyError_(e);
    throw e;
  } finally {
    lock.releaseLock();
  }
}

/** One-off test: starts a dry run on the develop branch ([TEST] email, nothing labelled). */
function testDispatch() {
  dispatch_({ dry_run: 'true', lookback_days: '1' }, 'develop');
  console.log('Test run started: check the Actions tab on GitHub, then your inbox.');
}

/** Run once to create the 5-minute trigger (safe to re-run: replaces the old one). */
function setup() {
  if (!PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN')) {
    throw new Error('Add the GITHUB_TOKEN script property first (Project Settings -> Script Properties).');
  }
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'checkAndDispatch')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkAndDispatch').timeBased().everyMinutes(CONFIG.checkEveryMinutes).create();
  console.log('Trigger created: checkAndDispatch every ' + CONFIG.checkEveryMinutes + ' minutes.');
}

function dispatch_(inputs, ref) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('GITHUB_TOKEN script property is missing.');
  const url = 'https://api.github.com/repos/' + CONFIG.repo + '/actions/workflows/' +
              CONFIG.workflow + '/dispatches';
  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({ ref: ref, inputs: inputs }),
    muteHttpExceptions: true,
  });
  const code = res.getResponseCode();
  if (code !== 204) {
    throw new Error('GitHub dispatch failed (HTTP ' + code + '): ' + res.getContentText().slice(0, 300));
  }
}

/** Emails you about a failure at most once a day (e.g. expired GitHub token). */
function notifyError_(e) {
  const props = PropertiesService.getScriptProperties();
  const today = Utilities.formatDate(new Date(), 'UTC', 'yyyy-MM-dd');
  if (props.getProperty('LAST_ERROR_MAIL') === today) return;
  props.setProperty('LAST_ERROR_MAIL', today);
  MailApp.sendEmail(
    Session.getEffectiveUser().getEmail(),
    '[BBG Digest] Trigger script error',
    'The Apps Script that starts the Bloomberg digest failed:\n\n' + e +
    '\n\nIf the GitHub token expired, create a new one and update the GITHUB_TOKEN script property.'
  );
}
