const fs = require('fs');
const path = require('path');
const https = require('https');

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const current = argv[i];
    if (!current.startsWith('--')) {
      continue;
    }
    const key = current.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    i += 1;
  }
  return args;
}

function parseJsonFile(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function resolveSecretsPath(preferredRoot) {
  const candidates = [];
  if (preferredRoot) {
    candidates.push(path.join(preferredRoot, 'secrets.json'));
  }
  if (process.env.USERPROFILE) {
    candidates.push(path.join(process.env.USERPROFILE, '.chatcode', 'secrets.json'));
  }
  candidates.push(path.join('C:\\Users\\Administrator', '.chatcode', 'secrets.json'));

  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(`No ChatCode secrets.json found. Tried: ${candidates.join(', ')}`);
}

function getLoginToken(secretsPath) {
  const json = parseJsonFile(secretsPath);
  const record = json['chinaunicom-software.chatcode'];
  if (!record || !record.loginToken) {
    throw new Error(`loginToken not found in ${secretsPath}`);
  }
  return record.loginToken;
}

function requestStats({ token, beginTime, endTime, url }) {
  const body = JSON.stringify({ beginTime, endTime });

  return new Promise((resolve, reject) => {
    const req = https.request(
      url,
      {
        method: 'POST',
        headers: {
          Authorization: token,
          'Content-Type': 'application/json;charset=UTF-8',
          'Content-Length': Buffer.byteLength(body, 'utf8'),
        },
      },
      (res) => {
        let raw = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          raw += chunk;
        });
        res.on('end', () => {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error(`Stats API failed with ${res.statusCode}: ${raw}`));
            return;
          }
          try {
            resolve(JSON.parse(raw));
          } catch (err) {
            reject(new Error(`Failed to parse stats response JSON: ${err.message}`));
          }
        });
      },
    );

    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function toNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function isMergeTitle(title) {
  if (!title) {
    return false;
  }
  return /^Merge /i.test(title);
}

function filterRows(rows, args) {
  return rows.filter((row) => {
    if (args['author-email']) {
      const email = String(args['author-email']).toLowerCase();
      if (String(row.email || row.authorEmail || '').toLowerCase() !== email) {
        return false;
      }
    }

    if (args['project-name'] && String(row.projectName || '') !== String(args['project-name'])) {
      return false;
    }

    if (args['gitlab-instance'] && String(row.gitlabInstance || '') !== String(args['gitlab-instance'])) {
      return false;
    }

    if (args['task-id']) {
      const taskTitle = `taskId:${args['task-id']}`;
      if (String(row.title || '') !== taskTitle) {
        return false;
      }
    }

    if (args['title-contains']) {
      if (!String(row.title || '').includes(String(args['title-contains']))) {
        return false;
      }
    }

    if (args['commit-id']) {
      if (String(row.id || '') !== String(args['commit-id'])) {
        return false;
      }
    }

    if (args['exclude-merge'] && isMergeTitle(row.title)) {
      return false;
    }

    return true;
  });
}

function summarizeRows(rows) {
  const additions = rows.reduce((sum, row) => sum + toNumber(row.additions), 0);
  const aiTotal = rows.reduce((sum, row) => sum + toNumber(row.aiTotal), 0);
  const total = rows.reduce((sum, row) => sum + toNumber(row.total), 0);
  const deletions = rows.reduce((sum, row) => sum + toNumber(row.deletions), 0);
  const aiRatioPercent = total > 0 ? Number(((aiTotal / total) * 100).toFixed(2)) : 0;

  return {
    commitCount: rows.length,
    additions,
    aiTotal,
    total,
    deletions,
    aiRatioPercent,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const beginTime = args['begin-time'];
  const endTime = args['end-time'];
  if (!beginTime || !endTime) {
    throw new Error('Missing required --begin-time or --end-time');
  }

  const chatCodeRoot = args['chatcode-root'];
  const secretsPath = resolveSecretsPath(chatCodeRoot);
  const token = getLoginToken(secretsPath);
  const url =
    args.url ||
    'https://chatcode.chinaunicom.cn/caassist-api-lt/caassist/api/stats/gitCommitRecord';

  const response = await requestStats({ token, beginTime, endTime, url });
  const rows = Array.isArray(response.data) ? response.data : [];
  const filteredRows = filterRows(rows, args);
  const summary = summarizeRows(filteredRows);

  const result = {
    ok: true,
    beginTime,
    endTime,
    url,
    secretsPath,
    filters: {
      authorEmail: args['author-email'] || null,
      projectName: args['project-name'] || null,
      gitlabInstance: args['gitlab-instance'] || null,
      taskId: args['task-id'] || null,
      titleContains: args['title-contains'] || null,
      commitId: args['commit-id'] || null,
      excludeMerge: Boolean(args['exclude-merge']),
    },
    summary,
    rows: filteredRows,
  };

  process.stdout.write(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  process.stdout.write(
    JSON.stringify(
      {
        ok: false,
        error: err.message || String(err),
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
});
