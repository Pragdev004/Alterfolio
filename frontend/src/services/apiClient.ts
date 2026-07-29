import axios from "axios";

import { API_BASE_URL } from "../utils/env";

const DEV_USER_ID =
  import.meta.env.VITE_AUTH_USER_ID ?? "11111111-1111-4111-8111-111111111111";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
    "X-User-Id": DEV_USER_ID,
  },
  timeout: 60000,
});
