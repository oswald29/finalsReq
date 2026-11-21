export interface AuthUser {
  id: number;
  email: string;
  name: string;
  monthlyBudget: number;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}
