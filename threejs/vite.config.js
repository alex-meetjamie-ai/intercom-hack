import {resolve} from 'node:path';
import {defineConfig,loadEnv} from 'vite';
export default defineConfig(({mode})=>{
  const env=loadEnv(mode,process.cwd(),'');
  const target=env.BACKEND_URL||'http://127.0.0.1:8740';
  const proxy={target,changeOrigin:true,ws:true,configure(server){
    const origin=request=>request.setHeader('Origin',target);
    server.on('proxyReq',origin);server.on('proxyReqWs',origin);
  }};
  return {server:{fs:{allow:[resolve(process.cwd(),'..')]},proxy:{'/api':proxy,'/sip':proxy}}};
});
