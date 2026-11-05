export const DISPUTE_TYPES = {
  DEPOSIT_DEDUCTION: { label: 'Deposit deduction', help: 'The owner kept some or all of your deposit and you disagree.' },
  FAKE_TO_LET: { label: 'Fake to-let', help: "The listing wasn't real, or the owner had no right to let it." },
  BAYNA_BREACH: { label: 'Bayna breach', help: 'The seller broke the token-money (bayna) agreement.' },
}

export const DISPUTE_STATUS = {
  OPEN: { label: 'Waiting for reply', tone: 'border-brass text-[#8a6410]' },
  UNDER_REVIEW: { label: 'With arbitrator', tone: 'border-tag-bachelor text-tag-bachelor' },
  RESOLVED: { label: 'Ruled', tone: 'border-gate text-gate' },
}

export const ALERT_RULES = {
  QR_SPAM: 'QR spam',
  RAPID_RELIST: 'Rapid relist',
  USER_BANNED: 'User banned',
  DISPUTE_RULED: 'Dispute ruled',
  QR_REVOKED: 'QR code revoked',
  KYC_DUPLICATE_ID: 'Duplicate ID, revoked',
  KYC_POSSIBLE_DUPLICATE: 'Look-alike ID, held for review',
  KYC_APPROVED: 'ID approved',
  KYC_REVOKED: 'ID revoked',
  KYC_RESTORED: 'ID restored',
}

export const QR_EVENTS = {
  ISSUED: 'Code issued',
  CONFIRMED: 'Scanned and confirmed',
  SCAN_REJECTED: 'Scan rejected',
  REVOKED: 'Code revoked',
}

export const CODE_STATES = {
  ACTIVE: { label: 'Live code', tone: 'border-brass text-[#8a6410]' },
  EXPIRED: { label: 'Expired', tone: 'border-ink-soft text-ink-soft' },
  USED: { label: 'Confirmed', tone: 'border-gate text-gate' },
  NONE: { label: 'No code', tone: 'border-ink-soft text-ink-soft' },
}

// Words for each side of a deal: rentals have tenants and owners, sales have buyers and sellers.
export const SIDE_LABELS = { TENANT: 'tenant', OWNER: 'owner', BUYER: 'buyer', SELLER: 'seller' }
