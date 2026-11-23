import { Suspense } from "react";
import SessionDetailsRoute from "../../../../page/giangvien/classroom/SessionDetailsRoute";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <SessionDetailsRoute />
    </Suspense>
  );
}
