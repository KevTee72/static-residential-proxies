#!/usr/bin/env node
// Node port of sticky_pool.py. Same rendezvous hashing, same CSV, so a Python
// worker and a Node worker send the same identity through the same proxy.
//
//   node pool.js --self-test
//   node pool.js proxies.csv account-0001 https://ipv4.icanhazip.com
//
// The mapping needs nothing outside Node. Sending a request needs undici:
//   npm install undici

const crypto = require('node:crypto')
const fs = require('node:fs')

function score(identity, proxyId) {
  return crypto.createHash('sha256').update(`${identity}|${proxyId}`).digest('hex')
}

function proxyFor(proxies, identity) {
  if (proxies.length === 0) throw new Error('the pool needs at least one proxy')
  return proxies.reduce((best, proxy) =>
    score(identity, proxy.id) > score(identity, best.id) ? proxy : best
  )
}

function loadProxies(path) {
  const [header, ...lines] = fs.readFileSync(path, 'utf8').trim().split(/\r?\n/)
  const names = header.split(',')
  return lines
    .map((line) => Object.fromEntries(line.split(',').map((value, i) => [names[i], value])))
    .filter((row) => row.http_port)
}

async function fetchThrough(proxy, url) {
  const { ProxyAgent, fetch } = require('undici')
  const options = { uri: `http://${proxy.host}:${proxy.http_port}` }
  if (proxy.username) {
    const pair = Buffer.from(`${proxy.username}:${proxy.password}`).toString('base64')
    options.token = `Basic ${pair}`
  }
  const response = await fetch(url, { dispatcher: new ProxyAgent(options) })
  return { status: response.status, body: (await response.text()).trim() }
}

function selfTest() {
  const proxies = [1, 2, 3, 4, 5].map((n) => ({ id: String(n) }))
  // What StickyPool.proxy_for() in sticky_pool.py returns for the same five ids.
  const expected = { 'account-0000': '1', 'account-0001': '2', 'account-0002': '2' }
  for (const [identity, pythonChoice] of Object.entries(expected)) {
    const first = proxyFor(proxies, identity).id
    const second = proxyFor([...proxies].reverse(), identity).id
    if (first !== second) throw new Error('mapping depends on proxy order')
    if (first !== pythonChoice) throw new Error(`${identity} differs from the Python mapping`)
    console.log(`${identity} -> proxy ${first}`)
  }
  console.log('stable across proxy order: ok')
  console.log('same mapping as sticky_pool.py: ok')
}

async function main() {
  const args = process.argv.slice(2)
  if (args[0] === '--self-test') return selfTest()
  if (args.length < 3) {
    console.error('usage: node pool.js proxies.csv IDENTITY URL')
    process.exit(2)
  }
  const [csvPath, identity, url] = args
  const proxy = proxyFor(loadProxies(csvPath), identity)
  console.log(`${identity} -> proxy ${proxy.id} (${proxy.host}, ${proxy.country}, ${proxy.isp})`)
  const result = await fetchThrough(proxy, url)
  console.log(`HTTP ${result.status}: ${result.body.slice(0, 200)}`)
}

main().catch((error) => {
  console.error(error.message)
  process.exit(1)
})
