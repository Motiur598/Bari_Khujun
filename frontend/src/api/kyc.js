import api from './client.js'

// The automated ID check. Resolves with { verified, kyc_status, message, mistakes } for every outcome, including a
// revoked card (which the API answers with 403).
export async function autoVerifyKyc({ docType, front, back }) {
  const body = new FormData()
  body.append('doc_type', docType)
  body.append('front', front)
  body.append('back', back)
  try {
    return (await api.post('/auth/kyc-auto-verify', body)).data
  } catch (err) {
    if (err.response?.status === 403 && err.response.data?.kyc_status === 'REVOKED') return err.response.data
    throw err
  }
}

// Admin: settle a card the check flagged ('approve', 'revoke' or 'restore').
export const decideKyc = async (userId, decision, note) =>
  (await api.post(`/admin/governance/users/${userId}/kyc/${decision}`, { note })).data

export const kycCardImagePath = (recordId, side) => `/admin/governance/kyc-verifications/${recordId}/images/${side}`

export const KYC_APPEAL_EMAIL = 'barikhujun.support@gmail.com'
