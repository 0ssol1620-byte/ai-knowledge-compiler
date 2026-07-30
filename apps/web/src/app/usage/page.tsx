import type { Metadata } from "next";

import { BillingManagement } from "@/components/billing-management";

export const metadata: Metadata = { title: "사용량 및 결제" };

export default function UsagePage() {
  return (
    <div className="simple-page usage-page">
      <p className="eyebrow">Usage & budget</p>
      <h1>사용량과 크레딧</h1>
      <p>
        처리 방식별 크레딧, 저장 공간과 구매 내역을 실제 원장 기준으로
        확인합니다.
      </p>
      <BillingManagement />
    </div>
  );
}
