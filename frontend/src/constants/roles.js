import { Building2, HandCoins, ShieldCheck, User, Users } from 'lucide-react'

// Tailwind needs complete class names, so each role spells out its own colour classes.
export const ROLES = {
  OWNER: {
    label: 'Owner',
    title: 'Property owner',
    blurb: 'Post your flat or house for rent or sale, with photos and its exact spot on the map.',
    kycHint: 'Owners verify with their National ID (NID).',
    icon: Building2,
    tagIdle: 'border-tag-owner text-tag-owner',
    tagActive: 'border-tag-owner bg-tag-owner text-white',
  },
  BACHELOR_TENANT: {
    label: 'Bachelor',
    title: 'Bachelor tenant',
    blurb: 'Find a seat or room in a shared flat. Run a bachelor flat (mess)? Sublet its free seats with photos.',
    kycHint: 'Add your NID, plus a student ID or job ID. Owners letting to bachelors look for both.',
    icon: User,
    tagIdle: 'border-tag-bachelor text-tag-bachelor',
    tagActive: 'border-tag-bachelor bg-tag-bachelor text-white',
  },
  FAMILY_TENANT: {
    label: 'Family',
    title: 'Family tenant',
    blurb: 'Flats for households, matched with owners who let to families.',
    kycHint: 'Add the NID of the person signing the lease. A job ID is optional.',
    icon: Users,
    tagIdle: 'border-tag-family text-tag-family',
    tagActive: 'border-tag-family bg-tag-family text-white',
  },
  BUYER: {
    label: 'Buyer',
    title: 'Property buyer',
    blurb: 'Browse flats and land for sale and deal with verified sellers.',
    kycHint: 'Buyers verify with their National ID (NID).',
    icon: HandCoins,
    tagIdle: 'border-tag-buyer text-[#8a6410]',
    tagActive: 'border-tag-buyer bg-tag-buyer text-ink',
  },
  ADMIN: {
    label: 'Admin',
    title: 'Administrator',
    blurb: 'Reviews identity documents and keeps listings honest.',
    kycHint: '',
    icon: ShieldCheck,
    tagIdle: 'border-ink text-ink',
    tagActive: 'border-ink bg-ink text-white',
  },
}

export const SELF_REGISTER_ROLES = ['OWNER', 'BACHELOR_TENANT', 'FAMILY_TENANT', 'BUYER']

// Roles that can be a party to a lease: owners, plus tenants (bachelor tenants can also sublet).
export const LEASE_ROLES = ['OWNER', 'BACHELOR_TENANT', 'FAMILY_TENANT']

export const KYC_DOC_TYPES = [
  { value: 'NID', label: 'National ID' },
  { value: 'STUDENT_ID', label: 'Student ID' },
  { value: 'JOB_ID', label: 'Job ID' },
]
