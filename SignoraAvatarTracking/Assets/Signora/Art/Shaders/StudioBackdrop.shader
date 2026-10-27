// Cyclorama backdrop for the sign-interpretation stage.
//
// Unlit on purpose: the backdrop must hold one predictable tone whatever the light rig does to the
// avatar, because the readability of the signing depends on the contrast between the hands and this
// surface. A single quad draws the whole cove - a soft pool of light behind the signer, edges
// falling off to keep the eye on the hands, and a darker band at the bottom standing in for the
// floor so there is no seam to look at.
Shader "Signora/StudioBackdrop"
{
    Properties
    {
        _GlowColor ("Glow Color", Color) = (0.431, 0.541, 0.608, 1)
        _EdgeColor ("Edge Color", Color) = (0.173, 0.239, 0.286, 1)
        _FloorColor ("Floor Color", Color) = (0.114, 0.157, 0.188, 1)
        _GlowCenter ("Glow Center (UV)", Vector) = (0.5, 0.423, 0, 0)
        _GlowRadius ("Glow Radius", Range(0.01, 1.5)) = 0.08
        _GlowSoftness ("Glow Softness", Range(0.01, 2)) = 0.48
        _GlowStretch ("Glow Stretch (horizontal)", Range(0.2, 4)) = 1
        _Horizon ("Floor Line (UV)", Range(0, 1)) = 0.182
        _CoveSoftness ("Cove Softness", Range(0.001, 0.6)) = 0.22
        _Dither ("Dither Strength", Range(0, 0.03)) = 0.006
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "Queue" = "Geometry" }
        LOD 100

        HLSLINCLUDE
        #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

        struct Attributes
        {
            float4 positionOS : POSITION;
            float2 uv         : TEXCOORD0;
            UNITY_VERTEX_INPUT_INSTANCE_ID
        };

        struct Varyings
        {
            float4 positionCS : SV_POSITION;
            float2 uv         : TEXCOORD0;
            UNITY_VERTEX_OUTPUT_STEREO
        };

        // Every pass declares this identically, which is what keeps the SRP Batcher able to batch
        // the backdrop with the rest of the scene.
        CBUFFER_START(UnityPerMaterial)
            half4  _GlowColor;
            half4  _EdgeColor;
            half4  _FloorColor;
            float4 _GlowCenter;
            float  _GlowRadius;
            float  _GlowSoftness;
            float  _GlowStretch;
            float  _Horizon;
            float  _CoveSoftness;
            float  _Dither;
        CBUFFER_END

        Varyings Vert(Attributes IN)
        {
            Varyings OUT = (Varyings)0;
            UNITY_SETUP_INSTANCE_ID(IN);
            UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(OUT);
            OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
            OUT.uv = IN.uv;
            return OUT;
        }
        ENDHLSL

        Pass
        {
            Name "Backdrop"
            Tags { "LightMode" = "UniversalForward" }
            // Two-sided so the quad reads the same whichever way it is turned to face the camera.
            Cull Off
            ZWrite On
            ZTest LEqual

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag

            half4 Frag(Varyings IN) : SV_Target
            {
                // The quad is mirrored when it is turned to face the camera, so fold the horizontal
                // axis about the glow centre - the pool of light stays centred either way.
                float2 d = IN.uv - _GlowCenter.xy;
                d.x = abs(d.x) / max(_GlowStretch, 1e-4);
                float glow = 1.0 - smoothstep(_GlowRadius, _GlowRadius + _GlowSoftness, length(d));

                half3 col = lerp(_EdgeColor.rgb, _GlowColor.rgb, glow);

                // Floor band. Squared so the cove eases in instead of drawing a visible horizon.
                float floorMask = 1.0 - smoothstep(_Horizon, _Horizon + _CoveSoftness, IN.uv.y);
                col = lerp(col, _FloorColor.rgb, floorMask * floorMask);

                // A gradient this wide and this shallow bands badly at 8 bits, which is exactly the
                // kind of moving artefact that pulls attention off the hands. Break it up.
                float noise = frac(sin(dot(IN.positionCS.xy, float2(12.9898, 78.233))) * 43758.5453);
                col += (noise - 0.5) * _Dither;

                return half4(col, 1.0);
            }
            ENDHLSL
        }

        // The PC pipeline asset asks for a depth texture, so the backdrop has to write depth like
        // any other opaque surface. Without this it is missing from _CameraDepthTexture and reads as
        // the far plane to anything depth-driven, such as depth of field added to the volume later.
        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }
            Cull Off
            ZWrite On
            ZTest LEqual
            ColorMask R

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment DepthFrag

            half4 DepthFrag(Varyings IN) : SV_Target
            {
                return 0;
            }
            ENDHLSL
        }
    }

    Fallback "Universal Render Pipeline/Unlit"
}
