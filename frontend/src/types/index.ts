export interface ChatMessage {
    id: string;
    sender: string;
    content: string;
    avatar: string;
    timestamp: string;
}
export interface User {
    id: string;
    name: string;
    avatar: string;
    isMicOn: boolean;
    isMicOff: boolean;
    isCameraOn: boolean;
    isCameraOff: boolean;
}
export interface TranScript {
    id: string;
    text: string;
    speaker: string;
    timestamp: string;
}