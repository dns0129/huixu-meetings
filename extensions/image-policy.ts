// Keep an explicitly requested image job on the configured model and prevent duplicate requests.
export default function (pi) {
  let requested = false;
  pi.on('tool_call', (event) => {
    if (event.toolName !== 'codex_generate_image') return;
    if (requested) return {block: true, terminate: true, reason: 'Only one image request is allowed for this job.'};
    const outputDir = process.env.PI_CODEX_IMAGE_SAVE_DIR;
    if (!outputDir) return {block: true, terminate: true, reason: 'Image output directory is missing.'};
    event.input.model = 'gpt-6.1-sol';
    event.input.transport = 'responses';
    event.input.outputFormat = 'png';
    event.input.save = 'custom';
    event.input.saveDir = outputDir;
    delete event.input.referencedImagePaths;
    delete event.input.numLastImagesToInclude;
    // The server supplies one authorized image for size adaptation. Never use a model-supplied path.
    const reference = process.env.MEETING_KV_REFERENCE;
    if (reference) event.input.referencedImagePaths = [reference];
    requested = true;
  });
}
