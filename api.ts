export async function api<T>(path:string, body?:unknown):Promise<T> {
  const response = await fetch(`/api${path}`, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if (!response.ok) {
    const data = await response.json().catch(()=>({detail:'Backend unavailable'}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request rejected (${response.status})`);
  }
  return response.json();
}
