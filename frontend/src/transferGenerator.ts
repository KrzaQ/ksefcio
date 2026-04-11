import type { DecryptedInvoice } from './stores/invoices'

export interface TransferConfig {
  senderAccount: string
  senderName: string
  titleTemplate: string
}

export function split35(s: string): string {
  const chunks: string[] = []
  for (let i = 0; i < s.length; i += 35) {
    chunks.push(s.substring(i, i + 35))
  }
  return chunks.join('|')
}

export function cleanAccount(account: string): string {
  return account.replace(/\D/g, '')
}

function stripQuotes(s: string): string {
  return s.replace(/"/g, '')
}

function sortCode(account: string): number {
  return parseInt(cleanAccount(account).substring(2, 10), 10)
}

function toGrosze(amount: string): number {
  return Math.round(parseFloat(amount) * 100)
}

function buildTitle(template: string, invoice: DecryptedInvoice): string {
  return template
    .replace(/\{their_id\}/g, invoice.invoice_number)
    .replace(/\{ksef_id\}/g, invoice.ksef_ref)
}

function generateTransferLine(invoice: DecryptedInvoice, config: TransferConfig, date: string): string {
  const senderClean = cleanAccount(config.senderAccount)
  const recipientClean = cleanAccount(invoice.bank_account!)

  return [
    '110',
    date,
    String(toGrosze(invoice.gross_amount)),
    String(sortCode(config.senderAccount)),
    '0',
    `"${senderClean}"`,
    `"${recipientClean}"`,
    `"${stripQuotes(split35(config.senderName))}"`,
    `"${stripQuotes(split35(invoice.seller_name))}"`,
    '0',
    String(sortCode(invoice.bank_account!)),
    `"${stripQuotes(split35(buildTitle(config.titleTemplate, invoice)))}"`,
    '""',
    '""',
    '"51"',
  ].join(',')
}

export function generateTransferFiles(
  invoices: DecryptedInvoice[],
  config: TransferConfig,
): string[] {
  const date = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Warsaw' }).replace(/-/g, '')
  const files: string[] = []
  for (let i = 0; i < invoices.length; i += 32) {
    const chunk = invoices.slice(i, i + 32)
    files.push(chunk.map(inv => generateTransferLine(inv, config, date)).join('\r\n'))
  }
  return files
}

export function downloadFile(content: string, filename: string): void {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
