using UnityEngine;

namespace Signora.Presentation
{
    /// <summary>
    /// Keeps the signing space in frame whatever shape the page gives the canvas.
    ///
    /// The stage element is fluid - roughly 1.5:1 on a desktop, squarer on a tablet, and taller than
    /// it is wide on a phone - and Unity's field of view is measured on the vertical axis, so a fixed
    /// FOV holds the head steady while the horizontal view narrows. On a narrow canvas that quietly
    /// crops the hands, which is the one part of the picture that carries the meaning.
    ///
    /// So instead of a fixed angle, this fits a box: a width and a height in metres that must both
    /// stay visible, fitted like `object-fit: contain`. Whichever axis is tighter decides the FOV and
    /// the other one gains slack, which costs nothing because the slack fills with backdrop.
    /// </summary>
    [RequireComponent(typeof(Camera))]
    [DisallowMultipleComponent]
    public sealed class SignoraCameraFraming : MonoBehaviour
    {
        [Tooltip("World-space point the frame is centred on - roughly the signer's sternum.")]
        [SerializeField] Vector3 focusPoint = new Vector3(0f, 0.98f, 0f);

        [Tooltip("Metres of signing space that must stay visible across the frame.")]
        [SerializeField] float framingWidth = 1.3f;

        [Tooltip("Metres of signing space that must stay visible up the frame.")]
        [SerializeField] float framingHeight = 1.12f;

        Camera m_Camera;
        float m_LastAspect = -1f;

        void Awake() => m_Camera = GetComponent<Camera>();

        void OnEnable()
        {
            m_LastAspect = -1f;
            Apply();
        }

        void LateUpdate()
        {
            // The canvas is resized by the page, not by us, so there is no event to hang this on.
            // Comparing the aspect is cheap and skips the trig on all but the frames that resize.
            if (Mathf.Approximately(m_Camera.aspect, m_LastAspect)) return;
            Apply();
        }

        [ContextMenu("Apply Framing Now")]
        void Apply()
        {
            if (m_Camera == null) m_Camera = GetComponent<Camera>();

            var aspect = Mathf.Max(m_Camera.aspect, 1e-4f);
            m_LastAspect = m_Camera.aspect;

            // Distance along the view axis rather than straight-line distance, so the box is fitted
            // to the plane the signer stands on and the camera can be moved without retuning this.
            var distance = Vector3.Dot(focusPoint - transform.position, transform.forward);
            if (distance <= 1e-4f) return;

            // Contain: satisfy the height outright, and satisfy the width by way of the aspect.
            var halfHeight = Mathf.Max(framingHeight * 0.5f, framingWidth * 0.5f / aspect);
            m_Camera.fieldOfView = Mathf.Clamp(2f * Mathf.Atan2(halfHeight, distance) * Mathf.Rad2Deg, 1f, 179f);
        }

#if UNITY_EDITOR
        void OnDrawGizmosSelected()
        {
            Gizmos.color = new Color(0.47f, 0.79f, 0.94f, 0.9f);
            Gizmos.matrix = Matrix4x4.TRS(focusPoint, transform.rotation, Vector3.one);
            Gizmos.DrawWireCube(Vector3.zero, new Vector3(framingWidth, framingHeight, 0f));
        }
#endif
    }
}
