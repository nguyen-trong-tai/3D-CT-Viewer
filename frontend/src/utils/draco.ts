import { DRACOLoader } from 'three-stdlib';

export const DRACO_DECODER_PATH = `${import.meta.env.BASE_URL}draco/`;

export const createDracoLoader = () => {
    const dracoLoader = new DRACOLoader();
    dracoLoader.setDecoderPath(DRACO_DECODER_PATH);
    return dracoLoader;
};
