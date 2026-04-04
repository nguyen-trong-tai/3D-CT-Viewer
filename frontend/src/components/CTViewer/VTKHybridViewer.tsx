import React, { useRef, useEffect, useState } from 'react';
import '@kitware/vtk.js/Rendering/Profiles/Volume';
import '@kitware/vtk.js/Rendering/Profiles/Geometry';

import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkVolume from '@kitware/vtk.js/Rendering/Core/Volume';
import vtkVolumeMapper from '@kitware/vtk.js/Rendering/Core/VolumeMapper';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';
import vtkPiecewiseFunction from '@kitware/vtk.js/Common/DataModel/PiecewiseFunction';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkImageData from '@kitware/vtk.js/Common/DataModel/ImageData';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray';
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData';
import vtkInteractorStyleTrackballCamera from '@kitware/vtk.js/Interaction/Style/InteractorStyleTrackballCamera';

import { ctApi, meshApi } from '../../services/api';
import * as THREE from 'three';
import { GLTFLoader } from 'three-stdlib';
import { createDracoLoader } from '../../utils/draco';

interface VTKHybridViewerProps {
    caseId: string;
}

const VTKHybridViewer: React.FC<VTKHybridViewerProps> = ({ caseId }) => {
    const vtkContainerRef = useRef<HTMLDivElement>(null);
    const context = useRef<any>(null);
    
    const [loadingMsg, setLoadingMsg] = useState<string>("Initializing...");

    useEffect(() => {
        if (!context.current && vtkContainerRef.current) {
            setLoadingMsg("Setting up VTK pipeline...");
            
            // 1. Setup render window
            const genericRenderWindow = vtkGenericRenderWindow.newInstance();
            genericRenderWindow.setContainer(vtkContainerRef.current);
            const renderer = genericRenderWindow.getRenderer();
            const renderWindow = genericRenderWindow.getRenderWindow();
            
            // Interaction explicitly configured to be like ThreeJS Trackball
            const interactor = genericRenderWindow.getInteractor();
            const trackballStyle = vtkInteractorStyleTrackballCamera.newInstance();
            interactor.setInteractorStyle(trackballStyle);

            renderer.setBackground(0.06, 0.07, 0.08); // Dark medical-style background

            // 2. Volume Pipeline Init
            const volumeMapper = vtkVolumeMapper.newInstance();
            // Tối ưu hóa sample distance để chất lượng nét hơn (0.5 là đẹp nhưng nặng, 1.0 là cân bằng, ở đây để 0.5)
            volumeMapper.setSampleDistance(0.5); 
            // Bật tính năng nội suy trên các cạnh của voxel để volume liền mạch thành khối mượt mà thay vì các lát xếp nếp
            const volumeActor = vtkVolume.newInstance();
            volumeActor.setMapper(volumeMapper);

            // Setting up Bone-like CT visualization preset
            const ctfun = vtkColorTransferFunction.newInstance();
            ctfun.addRGBPoint(-1024, 0.0, 0.0, 0.0);
            ctfun.addRGBPoint(-400, 0.86, 0.61, 0.29); // Some orange-ish tint for tissue
            ctfun.addRGBPoint(100, 0.9, 0.8, 0.7);    // Softer white for light tissue
            ctfun.addRGBPoint(400, 1.0, 1.0, 1.0);    // White for bones
            ctfun.addRGBPoint(3000, 1.0, 1.0, 1.0);

            const ofun = vtkPiecewiseFunction.newInstance();
            ofun.addPoint(-1024, 0.0);
            ofun.addPoint(-500, 0.0);
            ofun.addPoint(50, 0.05);   // Slightly visible soft tissue
            ofun.addPoint(200, 0.15);  // More visible bones/calcification
            ofun.addPoint(3000, 0.8);

            volumeActor.getProperty().setRGBTransferFunction(0, ctfun);
            volumeActor.getProperty().setScalarOpacity(0, ofun);
            // Quan trọng nhất để tránh hiện tượng lát cắt (slicing artifacts):
            volumeActor.getProperty().setInterpolationTypeToLinear(); // Ép nội suy tuyến tính
            volumeActor.getProperty().setShade(true);
            volumeActor.getProperty().setAmbient(0.2);
            volumeActor.getProperty().setDiffuse(0.7);
            volumeActor.getProperty().setSpecular(0.2);
            
            // 3. Mesh Pipeline Init
            const meshMapper = vtkMapper.newInstance();
            const meshActor = vtkActor.newInstance();
            meshActor.setMapper(meshMapper);
            meshActor.getProperty().setColor(1.0, 0.1, 0.1); // High contrast RED for tumor/organ
            meshActor.getProperty().setOpacity(1.0);         // Đã thay đổi thành Solid 100% để hiển thị nét khối u
            meshActor.getProperty().setAmbient(0.2);
            meshActor.getProperty().setDiffuse(0.8);
            meshActor.getProperty().setSpecular(0.5);
            meshActor.getProperty().setSpecularPower(50);

            // Add actors explicitly
            renderer.addVolume(volumeActor);
            renderer.addActor(meshActor);

            context.current = { genericRenderWindow, volumeActor, meshActor };

            const loadData = async () => {
                try {
                    // --- LOAD VOLUME ---
                    setLoadingMsg("Downloading CT Volume...");
                    const { data, shape, spacing } = await ctApi.getVolumeBinary(caseId);
                    
                    setLoadingMsg("Processing Volume...");
                    const volumeData = vtkImageData.newInstance({
                        // Backend data is passed as Int16Array unrolled. Tăng spacing Z nếu các lát cắt xa nhau
                        spacing: [spacing[0], spacing[1], spacing[2]],
                        origin: [0, 0, 0],
                        extent: [0, shape[0] - 1, 0, shape[1] - 1, 0, shape[2] - 1],
                    });
                    
                    const dataArray = vtkDataArray.newInstance({
                        values: data, 
                        numberOfComponents: 1,
                    });
                    volumeData.getPointData().setScalars(dataArray);
                    volumeMapper.setInputData(volumeData);
                    
                    renderer.resetCamera();
                    renderWindow.render();

                    // --- LOAD MESH ---
                    setLoadingMsg("Loading 3D Mesh...");
                    const loader = new GLTFLoader();
                    const dracoLoader = createDracoLoader();
                    loader.setDRACOLoader(dracoLoader);

                    loader.load(meshApi.getMeshUrl(caseId), (gltf: any) => {
                        let meshGeom: THREE.BufferGeometry | null = null;
                        
                        gltf.scene.traverse((child: any) => {
                            if (child.isMesh && !meshGeom) {
                                meshGeom = child.geometry;
                            }
                        });

                        if (meshGeom) {
                            setLoadingMsg("Converting Mesh to VTK format...");
                            const geom = meshGeom as THREE.BufferGeometry;
                            const polyData = vtkPolyData.newInstance();
                            
                            // 1. Vertices Data
                            const positions = geom.attributes.position.array;
                            polyData.getPoints().setData(positions as Float32Array, 3);

                            // 2. Faces (Indices) Data
                            if (geom.index) {
                                const indices = geom.index.array;
                                const polysCount = indices.length / 3;
                                const polysArray = new Uint32Array(polysCount * 4);
                                for (let i = 0; i < polysCount; i++) {
                                    polysArray[i * 4] = 3;
                                    polysArray[i * 4 + 1] = indices[i * 3];
                                    polysArray[i * 4 + 2] = indices[i * 3 + 1];
                                    polysArray[i * 4 + 3] = indices[i * 3 + 2];
                                }
                                polyData.getPolys().setData(polysArray);
                            } else {
                                // Face generation if no indices
                                const polyCount = positions.length / 9;
                                const polysArray = new Uint32Array(polyCount * 4);
                                for (let i = 0; i < polyCount; i++) {
                                    polysArray[i * 4] = 3;
                                    polysArray[i * 4 + 1] = i * 3;
                                    polysArray[i * 4 + 2] = i * 3 + 1;
                                    polysArray[i * 4 + 3] = i * 3 + 2;
                                }
                                polyData.getPolys().setData(polysArray);
                            }

                            meshMapper.setInputData(polyData);
                            
                            // Align Mesh visually to Volume center to fix the missing offset
                            geom.computeBoundingBox();
                            const vOrigin = volumeData.getCenter();
                            const bbCenter = geom.boundingBox ? [
                                (geom.boundingBox.max.x + geom.boundingBox.min.x) / 2,
                                (geom.boundingBox.max.y + geom.boundingBox.min.y) / 2,
                                (geom.boundingBox.max.z + geom.boundingBox.min.z) / 2
                            ] : [0, 0, 0];
                            
                            // Translate the actor to overlap accurately
                            meshActor.setPosition(
                                vOrigin[0] - bbCenter[0], 
                                vOrigin[1] - bbCenter[1], 
                                vOrigin[2] - bbCenter[2]
                            );
                            
                            renderer.resetCamera();
                            renderWindow.render();
                            setLoadingMsg(""); // Done
                        } else {
                            setLoadingMsg("No valid Mesh geometry found");
                        }
                    }, undefined, (e: any) => {
                        console.error('Failed to load mesh', e);
                        setLoadingMsg("Error loading Mesh.");
                    });

                } catch (e) {
                    console.error("VTK Render error: ", e);
                    setLoadingMsg("Error initializing renderer.");
                }
            };
            
            loadData();

            // Handle resize
            const onResize = () => {
                genericRenderWindow.resize();
            };
            window.addEventListener('resize', onResize);
            context.current.onResize = onResize;
        }

        return () => {
            if (context.current) {
                window.removeEventListener('resize', context.current.onResize);
                context.current.genericRenderWindow.delete();
                context.current = null;
            }
        };
    }, [caseId]);

    // UI Tools Handlers
    const setPreset = (type: string) => {
        if (!context.current) return;
        const volumeActor = context.current.volumeActor;
        const ctfun = vtkColorTransferFunction.newInstance();
        const ofun = vtkPiecewiseFunction.newInstance();

        if (type === 'bones') {
            ctfun.addRGBPoint(-1024, 0.0, 0.0, 0.0);
            ctfun.addRGBPoint(-400, 0.86, 0.61, 0.29); 
            ctfun.addRGBPoint(100, 0.9, 0.8, 0.7);    
            ctfun.addRGBPoint(400, 1.0, 1.0, 1.0);    
            ctfun.addRGBPoint(3000, 1.0, 1.0, 1.0);

            ofun.addPoint(-1024, 0.0);
            ofun.addPoint(-500, 0.0);
            ofun.addPoint(50, 0.05);   
            ofun.addPoint(200, 0.15);  
            ofun.addPoint(3000, 0.8);
        } else if (type === 'tissue') {
            ctfun.addRGBPoint(-1024, 0.0, 0.0, 0.0);
            ctfun.addRGBPoint(-100, 0.8, 0.5, 0.4); 
            ctfun.addRGBPoint(50, 0.9, 0.6, 0.5);    
            ctfun.addRGBPoint(200, 1.0, 0.9, 0.8);

            ofun.addPoint(-1024, 0.0);
            ofun.addPoint(-150, 0.0);
            ofun.addPoint(-50, 0.2);   
            ofun.addPoint(150, 0.6);  
            ofun.addPoint(3000, 0.9);
        }

        volumeActor.getProperty().setRGBTransferFunction(0, ctfun);
        volumeActor.getProperty().setScalarOpacity(0, ofun);
        context.current.genericRenderWindow.getRenderWindow().render();
    };

    return (
        <div style={{ width: '100%', height: '100%', position: 'relative', background: '#0f1115' }}>
            <div 
                ref={vtkContainerRef} 
                style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }} 
            />
            
            {/* Overlay loader text */}
            {loadingMsg && (
                <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', 
                              backgroundColor: 'rgba(0,0,0,0.7)', padding: '15px 25px', borderRadius: '8px', 
                              color: 'white', zIndex: 20, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                    <div style={{ width: '20px', height: '20px', border: '3px solid white', borderTop: '3px solid transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                    {loadingMsg}
                </div>
            )}
            
            {/* Quick Presets Menu */}
            <div style={{ position: 'absolute', bottom: 20, left: 20, zIndex: 10, display: 'flex', gap: '10px' }}>
                <button 
                    onClick={() => setPreset('bones')}
                    style={{ background: 'rgba(255,255,255,0.1)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', backdropFilter: 'blur(4px)' }}
                >
                    Preset: Core / Bones
                </button>
                <button 
                    onClick={() => setPreset('tissue')}
                    style={{ background: 'rgba(255,255,255,0.1)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', backdropFilter: 'blur(4px)' }}
                >
                    Preset: Soft Tissue
                </button>
            </div>
            <style>{`
                @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            `}</style>
        </div>
    );
};

export default VTKHybridViewer;
