export async function api(path, method = "GET", body, headers = {}) {
  const response = await fetch(path, {method, cache:"no-store", headers:{...headers,
    ...(body === undefined ? {} : {"Content-Type":"application/json"})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  if (response.status === 204) return null;
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error?.message || "The viewer request failed.");
    error.status = response.status;
    throw error;
  }
  return result;
}
