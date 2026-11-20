import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// DEM mesh with per-vertex colours; one vertex per (downsampled) pixel.
export class TerrainView {
  constructor(canvas) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(devicePixelRatio);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0f1115);
    this.camera = new THREE.PerspectiveCamera(45, 1, 10, 1e7);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    this.sun = new THREE.DirectionalLight(0xffffff, 1.6);
    this.scene.add(this.sun);
    this.setSun(225, 45);
    this.raycaster = new THREE.Raycaster();
    this.marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0x00e5ff }));
    this.marker.visible = false;
    this.scene.add(this.marker);
    this._loop = () => { this.raf = requestAnimationFrame(this._loop); this.controls.update(); this.renderer.render(this.scene, this.camera); };
    this._loop();
  }

  setSun(azimuthDeg, altitudeDeg) {
    const az = (azimuthDeg * Math.PI) / 180, alt = (altitudeDeg * Math.PI) / 180;
    // scene: x = east, y = up, z = south
    this.sun.position.set(Math.sin(az) * Math.cos(alt), Math.sin(alt), -Math.cos(az) * Math.cos(alt));
  }

  resize(w, h) {
    if (!w || !h) return; // hidden tab
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  setStack(stack) {
    if (this.mesh) { this.scene.remove(this.mesh); this.mesh.geometry.dispose(); }
    const { w, h, res } = stack;
    this.dims = { w, h, res };
    const geo = new THREE.PlaneGeometry((w - 1) * res, (h - 1) * res, w - 1, h - 1);
    geo.rotateX(-Math.PI / 2); // plane rows run north→south, matching raster rows
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(w * h * 3), 3));
    this.dem = Float32Array.from(stack.layers.DEM, (v) => (Number.isFinite(v) ? v : 0));
    this.mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true }));
    this.scene.add(this.mesh);
    const ext = Math.max(w, h) * res;
    this.marker.scale.setScalar(ext / 300);
    this.camera.position.set(0, ext * 0.55, ext * 0.75);
    this.controls.target.set(0, 0, 0);
  }

  setExaggeration(ex) {
    if (!this.mesh) return;
    const pos = this.mesh.geometry.attributes.position;
    for (let i = 0; i < this.dem.length; i++) pos.setY(i, this.dem[i] * ex);
    pos.needsUpdate = true;
    this.mesh.geometry.computeVertexNormals();
    this.mesh.geometry.computeBoundingSphere();
    this.ex = ex;
  }

  setColors(rgb) {
    const attr = this.mesh.geometry.attributes.color;
    attr.array.set(rgb);
    attr.needsUpdate = true;
  }

  // Screen point → raster index (or null)
  pick(clientX, clientY) {
    if (!this.mesh) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObject(this.mesh)[0];
    if (!hit) return null;
    const { w, h, res } = this.dims;
    const col = Math.round(hit.point.x / res + (w - 1) / 2);
    const row = Math.round(hit.point.z / res + (h - 1) / 2);
    if (col < 0 || row < 0 || col >= w || row >= h) return null;
    this.marker.position.copy(hit.point);
    this.marker.visible = true;
    return { row, col, i: row * w + col };
  }

  screenshot() { return this.renderer.domElement.toDataURL('image/png'); }

  dispose() { cancelAnimationFrame(this.raf); this.controls.dispose(); this.renderer.dispose(); }
}
