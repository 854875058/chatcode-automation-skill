const fs = require('fs');
const path = require('path');
const net = require('net');

const DELIMITER = '\f';

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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readPrompt(args) {
  if (args.prompt) {
    return String(args.prompt);
  }
  if (args['prompt-file']) {
    return fs.readFileSync(args['prompt-file'], 'utf8');
  }
  throw new Error('Missing required --prompt or --prompt-file');
}

function getTaskDir(chatcodeRoot, taskId) {
  return path.join(chatcodeRoot, 'globalStorage', 'chinaunicom-software.chatcode', 'tasks', taskId);
}

function extractCodeBlocks(text) {
  if (!text) {
    return [];
  }
  const matches = text.match(/```[\s\S]*?```/g);
  return matches || [];
}

function stripFence(block) {
  return block
    .replace(/^```[a-zA-Z0-9_-]*\s*/, '')
    .replace(/\s*```$/, '');
}

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function collectTaskResult(taskDir) {
  const uiPath = path.join(taskDir, 'ui_messages.json');
  const apiPath = path.join(taskDir, 'api_conversation_history.json');
  const uiMessages = readJsonIfExists(uiPath) || [];
  const apiMessages = readJsonIfExists(apiPath) || [];

  const completionMessages = uiMessages.filter(
    (item) => item && item.type === 'say' && item.say === 'completion_result' && typeof item.text === 'string',
  );
  const finalCompletion = completionMessages.length > 0 ? completionMessages[completionMessages.length - 1].text : '';

  const uiRaw = fs.existsSync(uiPath) ? fs.readFileSync(uiPath, 'utf8') : '';
  const apiRaw = fs.existsSync(apiPath) ? fs.readFileSync(apiPath, 'utf8') : '';

  const uiCodeBlocks = extractCodeBlocks(uiRaw);
  const apiCodeBlocks = extractCodeBlocks(apiRaw);
  const codeBlock = uiCodeBlocks[uiCodeBlocks.length - 1] || apiCodeBlocks[apiCodeBlocks.length - 1] || '';

  return {
    uiPath,
    apiPath,
    uiMessages,
    apiMessages,
    completionText: finalCompletion,
    codeBlock,
    code: codeBlock ? stripFence(codeBlock) : '',
  };
}

async function waitForTaskArtifacts(taskDir, timeoutMs, pollMs) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (fs.existsSync(path.join(taskDir, 'ui_messages.json'))) {
      return;
    }
    await sleep(pollMs);
  }
  throw new Error(`Timed out waiting for task artifacts in ${taskDir}`);
}

async function waitForCompletion(taskDir, timeoutMs, pollMs) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const result = collectTaskResult(taskDir);
    if (result.completionText || result.codeBlock) {
      return result;
    }
    await sleep(pollMs);
  }
  return collectTaskResult(taskDir);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const prompt = readPrompt(args);
  const pipeName = String(args.pipe || 'chatcode-ipc');
  const timeoutMs = Number(args['timeout-ms'] || 180000);
  const pollMs = Number(args['poll-ms'] || 1000);
  const chatcodeRoot = path.resolve(String(args['chatcode-root'] || path.join(process.env.USERPROFILE || '', '.chatcode')));

  const response = {
    ok: false,
    prompt,
    pipeName,
    timeoutMs,
    pollMs,
    chatcodeRoot,
    taskId: null,
    taskDir: null,
    completionText: '',
    codeBlock: '',
    code: '',
    events: [],
    error: null,
  };

  let clientId = null;
  let taskCompleted = false;
  let sent = false;
  let settled = false;

  function finish(socket, resolve, reject, err) {
    if (settled) {
      return;
    }
    settled = true;
    try {
      socket.end();
    } catch (closeErr) {
      // ignore
    }
    if (err) {
      response.error = err.message || String(err);
      reject(err);
    } else {
      resolve(response);
    }
  }

  const result = await new Promise((resolve, reject) => {
    const socketPath = `\\\\.\\pipe\\${pipeName}`;
    let buffer = '';
    const socket = net.createConnection(socketPath, async () => {
      console.error(`[chatcode] connected to ${socketPath}`);
    });

    socket.setEncoding('utf8');

    socket.on('data', async (chunk) => {
      buffer += chunk;
      const parts = buffer.split(DELIMITER);
      buffer = parts.pop();

      for (const part of parts) {
        if (!part) {
          continue;
        }
        let message;
        try {
          message = JSON.parse(part);
        } catch (err) {
          console.error('[chatcode] failed to parse message chunk');
          continue;
        }

        const data = message && message.data;
        if (!data) {
          continue;
        }

        if (data.type === 'Ack' && data.data && data.data.clientId) {
          clientId = data.data.clientId;
          response.events.push({ type: 'Ack', clientId });
          if (!sent) {
            sent = true;
            const payload = {
              type: 'message',
              data: {
                type: 'TaskCommand',
                origin: 'client',
                clientId,
                data: {
                  commandName: 'StartNewTask',
                  data: {
                    text: prompt,
                    images: [],
                    newTab: false,
                    configuration: {},
                  },
                },
              },
            };
            socket.write(JSON.stringify(payload) + DELIMITER, 'utf8');
            console.error('[chatcode] StartNewTask sent');
          }
          continue;
        }

        if (data.type === 'TaskEvent' && data.data) {
          const event = data.data;
          response.events.push(event);

          if (event.eventName === 'taskCreated') {
            response.taskId = event.payload && event.payload[0];
            response.taskDir = response.taskId ? getTaskDir(chatcodeRoot, response.taskId) : null;
            console.error(`[chatcode] taskCreated ${response.taskId}`);
            if (response.taskDir) {
              try {
                await waitForTaskArtifacts(response.taskDir, timeoutMs, pollMs);
              } catch (err) {
                finish(socket, resolve, reject, err);
                return;
              }
            }
          }

          if (event.eventName === 'taskCompleted') {
            taskCompleted = true;
            console.error('[chatcode] taskCompleted');
            if (response.taskDir) {
              const taskResult = await waitForCompletion(response.taskDir, timeoutMs, pollMs);
              response.ok = true;
              response.completionText = taskResult.completionText;
              response.codeBlock = taskResult.codeBlock;
              response.code = taskResult.code;
              finish(socket, resolve, reject, null);
              return;
            }
          }
        }
      }
    });

    socket.on('error', (err) => {
      finish(socket, resolve, reject, err);
    });

    socket.on('close', async () => {
      if (settled) {
        return;
      }
      if (taskCompleted && response.taskDir) {
        const taskResult = await waitForCompletion(response.taskDir, timeoutMs, pollMs);
        response.ok = true;
        response.completionText = taskResult.completionText;
        response.codeBlock = taskResult.codeBlock;
        response.code = taskResult.code;
        finish(socket, resolve, reject, null);
        return;
      }
      finish(socket, resolve, reject, new Error('IPC connection closed before task completed'));
    });

    setTimeout(async () => {
      if (settled) {
        return;
      }
      if (response.taskDir) {
        const taskResult = await waitForCompletion(response.taskDir, 0, pollMs);
        response.completionText = taskResult.completionText;
        response.codeBlock = taskResult.codeBlock;
        response.code = taskResult.code;
      }
      finish(socket, resolve, reject, new Error('Timed out waiting for ChatCode task completion'));
    }, timeoutMs);
  });

  process.stdout.write(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  const result = {
    ok: false,
    error: err.message || String(err),
  };
  process.stdout.write(JSON.stringify(result, null, 2));
  process.exitCode = 1;
});
