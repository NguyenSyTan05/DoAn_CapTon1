import api from "./api";

// Sinh viên tham gia lớp bằng mã lớp và xem các lớp của mình.
const joinClassByCode = async (code) => {
  const res = await api.post("/auth/student/classes/join", { code });
  return res.data;
};

const getMyClasses = async () => {
  const res = await api.get("/auth/student/classes");
  return res.data.classes;
};

// Phiên học mà sinh viên đang vào (chỉ khi đã là thành viên của lớp)
const getSession = async (sessionId) => {
  const res = await api.get(`/auth/student/sessions/${encodeURIComponent(sessionId)}`);
  return res.data.session;
};

// Điểm danh vào/ra phiên học (join chỉ thành công khi phiên đang LIVE)
const joinSession = async (sessionId) => {
  const res = await api.post(`/auth/student/sessions/${encodeURIComponent(sessionId)}/join`);
  return res.data;
};

const leaveSession = async (sessionId) => {
  const res = await api.post(`/auth/student/sessions/${encodeURIComponent(sessionId)}/leave`);
  return res.data;
};

export default { joinClassByCode, getMyClasses, getSession, joinSession, leaveSession };
