import {resolve} from 'node:path';
import {defineConfig,loadEnv} from 'vite';
export default defineConfig(({mode})=>{
  const env=loadEnv(mode,process.cwd(),'');
  const target=env.BACKEND_URL||'http://127.0.0.1:8740';
  const proxy={target,changeOrigin:true,ws:true,configure(server){
    const origin=request=>request.setHeader('Origin',target);
    server.on('proxyReq',origin);server.on('proxyReqWs',origin);
  }};
  return {define:{'import.meta.env.VITE_WEBSITE_URL':JSON.stringify(target),'import.meta.env.VITE_ADMIN_URL':JSON.stringify(env.VITE_ADMIN_URL||new URL('/admin',target).href)},server:{fs:{allow:[resolve(process.cwd(),'..')]},proxy:{'/api':proxy,'/sip':proxy,'/employee':proxy}}};
});
